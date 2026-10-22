import { createHash, randomUUID } from 'node:crypto';
import { now, today, hoursAfter, researchFile } from './store.js';
import { grantSchema } from './validation.js';
import { score, effective, normalize, staffContext, eligibility } from './matching.js';
import { semantic, modelStatus } from './embeddings.js';
import { federal, approvedPage } from './sources.js';
export const dispositions = [
  'Pursue',
  'Letter of inquiry',
  'Cultivate',
  'Monitor',
  'Partner blocked',
  'Do not pursue',
  'Review history',
  'Verify cycle',
];
export function keywordPlan(
  p,
  cursor,
  library = researchFile('search_keywords.json', { groups: [] }),
) {
  const core = [
    'vision care',
    'eye health',
    'vision screening',
    'eye care',
    'cataract surgery',
    'healthcare access',
  ];
  const groups = library.groups;
  const interleaved = [];
  for (let i = 0; i < Math.max(0, ...groups.map((g) => g.terms.length)); i++)
    for (const g of groups) if (g.terms[i]) interleaved.push(g.terms[i]);
  const seen = new Set(core),
    pool = [...p.funding_interests, ...interleaved].filter((v) => {
      const k = v.trim().toLowerCase();
      if (!k || seen.has(k)) return false;
      seen.add(k);
      return true;
    });
  const n = Math.min(18, pool.length);
  return {
    terms: [...core, ...Array.from({ length: n }, (_, i) => pool[(cursor + i) % pool.length])],
    cursor: pool.length ? (cursor + n) % pool.length : 0,
  };
}
const fingerprint = (r) =>
  createHash('sha256')
    .update(
      r.funder_name === 'Unknown' || !r.deadline
        ? `${r.source}|${r.source_id}`
        : `${normalize(r.grant_title)}|${normalize(r.funder_name)}|${r.deadline}`,
    )
    .digest('hex');
export async function assess(item, profile) {
  const { record, state } = effective(item);
  const result = score(
    record,
    profile,
    eligibility(record, profile).status === 'Ineligible' ? {} : await semantic(record, profile),
  );
  if (['source_changed', 'expired'].includes(state) && result.eligibility_status !== 'Ineligible') {
    result.eligibility_status = 'Needs Review';
    result.recommendation = 'Needs Review';
    result.warnings.push('Staff verification needs renewal.');
  }
  return result;
}
export async function rescore(s) {
  for (const g of s.grants) g.assessment = await assess(g, s.profile);
}
export async function upsert(s, raw) {
  const record = grantSchema.parse(raw),
    fp = fingerprint(record);
  let g =
    s.grants.find((g) =>
      g.sources.some((x) => x.source === record.source && x.source_id === record.source_id),
    ) || s.grants.find((g) => g.fingerprint === fp);
  const added = !g;
  if (!g) {
    g = {
      id: Math.max(0, ...s.grants.map((g) => g.id)) + 1,
      fingerprint: fp,
      record,
      sources: [],
      reviews: [],
      pipeline: null,
      date_discovered: now(),
    };
    s.grants.push(g);
  }
  const source = {
    source: record.source,
    source_id: record.source_id,
    source_url: record.source_url,
    last_checked: record.last_checked,
    raw_text: record.raw_text,
  };
  const existing = g.sources.find(
    (x) => x.source === source.source && x.source_id === source.source_id,
  );
  if (existing) Object.assign(existing, source);
  else g.sources.push(source);
  // Imported source facts never overwrite staff pipeline fields or review history.
  g.record = record;
  g.fingerprint = fp;
  g.assessment = await assess(g, s.profile);
  return added;
}
export function views(s) {
  return s.grants.map((g) => ({ ...g, ...effective(g), staff_context: staffContext(g, s) }));
}
export function filterGrants(items, q = {}) {
  const min = Number(q.min_score || 0),
    amount = Number(q.amount_min || 0);
  if (!Number.isFinite(min) || !Number.isFinite(amount))
    throw new Error('Enter valid numeric filters.');
  return items
    .filter((g) => {
      const r = g.record,
        a = g.assessment || {};
      if (!q.include_closed && ['closed', 'archived'].includes(r.grant_status)) return false;
      if (!q.include_staff_hidden && g.staff_context?.hidden) return false;
      if (
        (a.fit_score || 0) < min ||
        (amount &&
          Math.max(-1, ...[r.award_min, r.award_max, r.estimated_award].filter((v) => v !== null)) <
            amount)
      )
        return false;
      if (q.deadline && (!r.deadline || r.deadline < today() || r.deadline > q.deadline))
        return false;
      const haystack = normalize(
        [
          r.grant_title,
          r.funder_name,
          r.description,
          ...r.categories,
          ...r.program_areas,
          ...r.populations_served,
          ...r.geographic_restrictions,
        ].join(' '),
      );
      if (
        normalize(q.q)
          .split(' ')
          .some((t) => !haystack.includes(t))
      )
        return false;
      const fields = {
        funder: r.funder_name,
        geography: r.geographic_restrictions.join(' '),
        population: r.populations_served.join(' '),
        category: r.categories.join(' '),
        source: r.source,
      };
      if (
        Object.entries(fields).some(
          ([k, v]) => q[k] && !v.toLowerCase().includes(q[k].toLowerCase()),
        )
      )
        return false;
      if (q.eligibility && q.eligibility !== a.eligibility_status) return false;
      if (q.pipeline_status && q.pipeline_status !== (g.pipeline?.status || 'Discovered'))
        return false;
      return true;
    })
    .sort(
      (a, b) =>
        (b.assessment?.fit_score || 0) - (a.assessment?.fit_score || 0) ||
        (a.record.deadline || '9999').localeCompare(b.record.deadline || '9999') ||
        a.record.grant_title.localeCompare(b.record.grant_title),
    );
}
export function status(s) {
  const alive =
    !!s.schedule.heartbeat_at && Date.now() - Date.parse(s.schedule.heartbeat_at) < 100000;
  return {
    schedule: s.schedule,
    worker: alive ? 'available' : 'unavailable',
    running: !!s.lease && s.lease.expires > Date.now(),
    latest: s.runs.at(-1) || null,
    model: modelStatus(),
  };
}
export function createDiscovery(
  store,
  config,
  { fetchFederal = federal, fetchPage = approvedPage } = {},
) {
  let timer = null,
    pending = null,
    stopping = false;
  async function run({ scheduled = false } = {}) {
    if (pending) return pending;
    pending = (async () => {
      const token = await store.acquireLease({ scheduled });
      if (!token) return false;
      const id = randomUUID();
      let lost = false;
      const renewal = setInterval(
        () =>
          store
            .renewLease(token)
            .then((ok) => {
              if (!ok) lost = true;
            })
            .catch(() => {
              lost = true;
            }),
        30000,
      );
      renewal.unref();
      const errors = [],
        stats = { found: 0, rejected: 0, truncated: false };
      let added = 0,
        updated = 0;
      try {
        const snapshot = await store.update((s) => {
          s.runs.push({
            id,
            status: 'running',
            started_at: now(),
            finished_at: null,
            found: 0,
            added: 0,
            updated: 0,
            rejected: 0,
            errors: [],
          });
          s.runs = s.runs.slice(-100);
          s.schedule.last_started_at = now();
          s.schedule.last_status = 'running';
          const plan = keywordPlan(s.profile, s.cursor, s.keywordLibrary);
          s.cursor = plan.cursor;
          return { plan, sources: s.sources.filter((x) => x.enabled && x.terms_reviewed) };
        });
        const save = async (record) => {
          if (lost) throw new Error('Discovery lease lost; stopped to avoid duplicate writes.');
          await store.update(async (s) => {
            if (s.lease?.token !== token) throw new Error('Discovery lease lost.');
            const isNew = await upsert(s, record);
            if (isNew) added++;
            else updated++;
            const r = s.runs.find((r) => r.id === id);
            Object.assign(r, { found: stats.found, added, updated, rejected: stats.rejected });
          });
        };
        for await (const record of fetchFederal(snapshot.plan.terms, config.maxRecords, {
          stats,
          errors,
        })) {
          if (stopping) throw new Error('Server shutting down; refresh interrupted.');
          await save(record);
        }
        for (const source of snapshot.sources) {
          if (stopping) throw new Error('Server shutting down; refresh interrupted.');
          try {
            await save(await fetchPage(source));
          } catch (e) {
            errors.push(`${source.name}: ${e.message}`);
          }
        }
      } catch (e) {
        errors.push(e.message);
      } finally {
        clearInterval(renewal);
        await store.update((s) => {
          if (s.lease?.token !== token) return;
          const result = stopping
            ? 'interrupted'
            : errors.length
              ? added + updated
                ? 'partial'
                : 'failed'
              : 'success';
          const r = s.runs.find((r) => r.id === id);
          if (r)
            Object.assign(r, {
              status: result,
              finished_at: now(),
              found: stats.found,
              added,
              updated,
              rejected: stats.rejected,
              errors: errors.slice(0, 200),
            });
          s.schedule.last_status = result;
          s.schedule.last_finished_at = now();
          s.schedule.last_error = errors[0] || '';
          s.schedule.next_run_at = hoursAfter(
            result === 'failed' ? 0.25 : s.schedule.interval_hours,
          );
          s.lease = null;
        });
      }
      return true;
    })().finally(() => {
      pending = null;
    });
    return pending;
  }
  async function tick() {
    if (stopping) return;
    const due = await store.update((s) => {
      s.schedule.heartbeat_at = now();
      return s.schedule.enabled && s.schedule.next_run_at <= now();
    });
    if (due && !pending) await run({ scheduled: true });
  }
  return {
    run,
    start() {
      if (!config.scheduler) return;
      tick().catch(console.error);
      timer = setInterval(() => tick().catch(console.error), 30000);
      timer.unref();
    },
    async stop() {
      stopping = true;
      clearInterval(timer);
      if (pending) await pending;
    },
  };
}
