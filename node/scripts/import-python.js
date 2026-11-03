import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { DatabaseSync } from 'node:sqlite';
import { configuration } from '../config.js';
import { createStore, now } from '../store.js';
import { profileSchema, grantSchema, pipelineSchema } from '../validation.js';
import { rescore } from '../service.js';
export async function importPython(store, filename) {
  const db = new DatabaseSync(path.resolve(filename), { readOnly: true });
  try {
    const has = (t) =>
      !!db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name=?").get(t);
    const rows = (t) => (has(t) ? db.prepare(`SELECT * FROM ${t}`).all() : []);
    const json = (v) => (typeof v === 'string' ? JSON.parse(v) : v);
    const organization = rows('organizations')[0];
    if (!organization) throw new Error('Source has no organization profile.');
    const sources = rows('source_records'),
      reviews = rows('grant_reviews'),
      pipelines = rows('pipeline_entries');
    const grants = rows('grants').map((g) => ({
      id: g.id,
      fingerprint: g.fingerprint,
      record: grantSchema.parse(json(g.details)),
      date_discovered: g.date_discovered,
      sources: sources.filter((x) => x.grant_id === g.id),
      reviews: reviews
        .filter((x) => x.grant_id === g.id)
        .sort((a, b) => a.id - b.id)
        .map((r) => ({ ...r, facts: json(r.facts) })),
      pipeline: pipelines.find((x) => x.grant_id === g.id)
        ? pipelineSchema.parse(pipelines.find((x) => x.grant_id === g.id))
        : null,
    }));
    await store.update(async (s) => {
      if (s.grants.length || s.runs.length || s.sources.length || s.imported)
        throw new Error('Destination must be unused; create a new Node database before importing.');
      s.profile = profileSchema.parse(json(organization.profile));
      s.grants = grants;
      s.sources = rows('approved_sources').map((x) => ({
        ...x,
        enabled: !!x.enabled,
        terms_reviewed: !!x.terms_reviewed,
        selectors: json(x.selectors),
      }));
      s.prospects = rows('research_prospects').map((x) => ({ ...x, original: json(x.original) }));
      s.runs = rows('refresh_runs')
        .map((r) => ({ ...r, errors: json(r.errors), source_stats: json(r.source_stats) }))
        .slice(-100);
      s.cursor = rows('search_cursor')[0]?.position || 0;
      const schedule = rows('search_schedule')[0];
      if (schedule) s.schedule = { ...s.schedule, ...schedule };
      s.schedule.enabled = false;
      s.schedule.heartbeat_at = null;
      s.lease = null;
      s.imported = { at: now(), source: 'Python SQLite', grants: grants.length };
      // Python and JS revision encodings differ. Preserve evidence and require renewal,
      // rather than silently applying an old verification to different source facts.
      await rescore(s);
    });
    return { grants: grants.length, pipeline: pipelines.length, reviews: reviews.length };
  } finally {
    db.close();
  }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const file = process.argv[2];
  if (!file)
    throw new Error('Usage: npm run import:python -- /path/to/stopped-or-backed-up/grantiq.db');
  const store = await createStore(configuration());
  try {
    console.log(await importPython(store, file));
    console.log('Imported. Schedule paused; verify data and renew staff evidence before enabling.');
  } finally {
    await store.close();
  }
}
