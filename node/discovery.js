import { randomUUID } from 'node:crypto';
import { now, hoursAfter } from './store.js';
import { federal, approvedPage } from './sources.js';
import { keywordPlan, upsert } from './service.js';

/**
 * Recurring worker lifecycle. A database lease prevents overlapping runs during
 * Railway deploys; a heartbeat makes availability visible to staff.
 * Source failures produce partial results without deleting saved grants.
 */
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
