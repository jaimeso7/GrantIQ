import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import YAML from 'yaml';
import { root } from './config.js';
import { profileSchema } from './validation.js';
export const now = () => new Date().toISOString();
export const today = () => now().slice(0, 10);
export const hoursAfter = (hours) => new Date(Date.now() + hours * 3600000).toISOString();
export function researchFile(name, fallback) {
  for (const dir of ['config', 'config/examples']) {
    const p = path.join(root, dir, name);
    if (fs.existsSync(p)) return JSON.parse(fs.readFileSync(p, 'utf8'));
  }
  return fallback;
}
export function initialState() {
  const config = YAML.parse(fs.readFileSync(path.join(root, 'config/organization.yaml'), 'utf8'));
  const profile = profileSchema.parse(config.organization || config);
  const funders = researchFile('existing_funders.json', { funders: [] });
  profile.excluded_funders = [
    ...new Set([...profile.excluded_funders, ...(funders.funders || []).map((f) => f.name)]),
  ];
  profile.existing_funder_relationships = [
    ...new Set([
      ...profile.existing_funder_relationships,
      ...(funders.funders || []).map((f) => f.name),
    ]),
  ];
  const prospects = researchFile('research_prospects.json', []);
  return {
    version: 1,
    profile,
    keywordLibrary: researchFile('search_keywords.json', { groups: [] }),
    funderRegister: funders,
    grants: [],
    sources: [],
    prospects: prospects.map((p) => ({
      id: p.id,
      original: p,
      disposition: p.disposition,
      review_on: p.review_on || null,
      team_notes: '',
    })),
    runs: [],
    cursor: 0,
    schedule: {
      enabled: true,
      interval_hours: 6,
      next_run_at: hoursAfter(6),
      heartbeat_at: null,
      last_status: 'waiting',
    },
    lease: null,
    loginAttempts: {},
    imported: null,
  };
}
// One transactional workspace document is intentional for the bounded MVP.
// PostgreSQL row locks serialize updates across processes; never use filesystem state in production.
export async function createStore(config, seed = initialState) {
  let pool, sqlite;
  let queue = Promise.resolve();
  if (config.databaseUrl) {
    const { Pool } = await import('pg');
    pool = new Pool({
      connectionString: config.databaseUrl,
      max: 4,
      ssl: config.databaseSsl ? { rejectUnauthorized: true } : false,
      connectionTimeoutMillis: 10000,
    });
    await pool.query(
      'CREATE TABLE IF NOT EXISTS grantiq_node_workspace (id INTEGER PRIMARY KEY, payload JSONB NOT NULL)',
    );
    await pool.query(
      'INSERT INTO grantiq_node_workspace (id,payload) VALUES (1,$1) ON CONFLICT (id) DO NOTHING',
      [JSON.stringify(seed())],
    );
  } else {
    fs.mkdirSync(config.dataDir, { recursive: true });
    const { DatabaseSync } = await import('node:sqlite');
    sqlite = new DatabaseSync(path.join(config.dataDir, 'grantiq.sqlite'));
    sqlite.exec(
      'PRAGMA journal_mode=WAL; PRAGMA busy_timeout=10000; CREATE TABLE IF NOT EXISTS workspace (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)',
    );
    sqlite.prepare('INSERT OR IGNORE INTO workspace VALUES (1,?)').run(JSON.stringify(seed()));
  }
  async function read() {
    if (pool)
      return (await pool.query('SELECT payload FROM grantiq_node_workspace WHERE id=1')).rows[0]
        .payload;
    await queue;
    return JSON.parse(sqlite.prepare('SELECT payload FROM workspace WHERE id=1').get().payload);
  }
  function update(fn) {
    const task = queue.then(async () => {
      if (pool) {
        const c = await pool.connect();
        try {
          await c.query('BEGIN');
          const s = (
            await c.query('SELECT payload FROM grantiq_node_workspace WHERE id=1 FOR UPDATE')
          ).rows[0].payload;
          const result = await fn(s);
          await c.query('UPDATE grantiq_node_workspace SET payload=$1 WHERE id=1', [
            JSON.stringify(s),
          ]);
          await c.query('COMMIT');
          return result;
        } catch (e) {
          await c.query('ROLLBACK');
          throw e;
        } finally {
          c.release();
        }
      }
      sqlite.exec('BEGIN IMMEDIATE');
      try {
        const s = JSON.parse(
          sqlite.prepare('SELECT payload FROM workspace WHERE id=1').get().payload,
        );
        const result = await fn(s);
        sqlite.prepare('UPDATE workspace SET payload=? WHERE id=1').run(JSON.stringify(s));
        sqlite.exec('COMMIT');
        return result;
      } catch (e) {
        sqlite.exec('ROLLBACK');
        throw e;
      }
    });
    queue = task.catch(() => {});
    return task;
  }
  await update((s) => {
    s.keywordLibrary ??= researchFile('search_keywords.json', { groups: [] });
    s.funderRegister ??= researchFile('existing_funders.json', { funders: [] });
  });
  return {
    read,
    update,
    close: async () => {
      await queue;
      if (pool) await pool.end();
      else sqlite.close();
    },
    async acquireLease({ scheduled = false } = {}) {
      const token = randomUUID();
      return update((s) => {
        if (scheduled && (!s.schedule.enabled || s.schedule.next_run_at > now())) return null;
        if (s.lease && s.lease.expires > Date.now()) return null;
        for (const r of s.runs.filter((r) => r.status === 'running')) {
          r.status = 'interrupted';
          r.finished_at = now();
          r.errors.push('Previous worker stopped before completing.');
        }
        s.lease = { token, expires: Date.now() + 120000 };
        return token;
      });
    },
    async renewLease(token) {
      return update((s) => {
        if (s.lease?.token !== token) return false;
        s.lease.expires = Date.now() + 120000;
        return true;
      });
    },
  };
}
