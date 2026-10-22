import { test } from 'node:test';
import assert from 'node:assert/strict';
import { tempStore, record } from './helpers.js';
import { upsert, createDiscovery, filterGrants, views } from '../service.js';
import { keywordPlan } from '../service.js';
import { staffContext } from '../matching.js';
test('persisted research vocabulary and aliases work without private configuration files', async (t) => {
  const { store } = await tempStore(t);
  await store.update((s) => {
    s.keywordLibrary = { groups: [{ terms: ['special research phrase'] }] };
    s.funderRegister = { funders: [{ name: 'Example Foundation', aliases: ['Example Alias'] }] };
    s.profile.excluded_funders = ['Example Foundation'];
  });
  const s = await store.read();
  assert.ok(keywordPlan(s.profile, 0, s.keywordLibrary).terms.includes('special research phrase'));
  assert.equal(staffContext({ record: record({ funder_name: 'Example Alias' }) }, s).hidden, true);
});
test('transactions serialize concurrent staff updates and roll back failures', async (t) => {
  const { store } = await tempStore(t);
  await Promise.all(
    Array.from({ length: 20 }, () =>
      store.update((s) => {
        s.cursor++;
      }),
    ),
  );
  assert.equal((await store.read()).cursor, 20);
  await assert.rejects(
    store.update((s) => {
      s.cursor = 99;
      throw new Error('rollback');
    }),
  );
  assert.equal((await store.read()).cursor, 20);
});
test('refresh preserves staff-owned data and source identities', async (t) => {
  const { store } = await tempStore(t);
  await store.update(async (s) => {
    await upsert(s, record());
    s.grants[0].pipeline = { status: 'Applying', notes: 'Keep me' };
    await upsert(s, record({ description: 'Updated' }));
  });
  const s = await store.read();
  assert.equal(s.grants.length, 1);
  assert.equal(s.grants[0].pipeline.notes, 'Keep me');
  assert.equal(s.grants[0].sources.length, 1);
});
test('one lease prevents overlapping searches', async (t) => {
  const { store } = await tempStore(t);
  const results = await Promise.all([store.acquireLease(), store.acquireLease()]);
  assert.equal(results.filter(Boolean).length, 1);
  assert.equal(await store.renewLease('wrong'), false);
});
test('expired lease marks interrupted run and permits recovery', async (t) => {
  const { store } = await tempStore(t);
  await store.update((s) => {
    s.lease = { token: 'old', expires: 0 };
    s.runs.push({ status: 'running', errors: [] });
  });
  assert.ok(await store.acquireLease());
  assert.equal((await store.read()).runs[0].status, 'interrupted');
});
test('scheduled lease rechecks due time atomically, manual search can still run', async (t) => {
  const { store } = await tempStore(t);
  assert.equal(await store.acquireLease({ scheduled: true }), null);
  await store.update((s) => {
    s.schedule.enabled = true;
    s.schedule.next_run_at = '2099-01-01T00:00:00Z';
  });
  assert.equal(await store.acquireLease({ scheduled: true }), null);
  assert.ok(await store.acquireLease());
});
test('search persists counts, completion and schedule across worker instances', async (t) => {
  const { store, config } = await tempStore(t);
  const fetchFederal = async function* (_terms, _limit, { stats }) {
    stats.found = 1;
    yield record();
  };
  await createDiscovery(store, config, { fetchFederal }).run();
  let s = await store.read();
  assert.equal(s.runs[0].status, 'success');
  assert.equal(s.runs[0].added, 1);
  assert.equal(s.lease, null);
  await createDiscovery(store, config, { fetchFederal }).run();
  s = await store.read();
  assert.equal(s.runs[1].updated, 1);
});
test('partial collection remains visible and existing grants survive failures', async (t) => {
  const { store, config } = await tempStore(t);
  const fetchFederal = async function* (_t, _m, { errors }) {
    yield record();
    errors.push('bounded collection');
  };
  await createDiscovery(store, config, { fetchFederal }).run();
  assert.equal((await store.read()).runs[0].status, 'partial');
  const failed = async function* () {
    throw new Error('source offline');
  };
  await createDiscovery(store, config, { fetchFederal: failed }).run();
  const s = await store.read();
  assert.equal(s.runs[1].status, 'failed');
  assert.equal(s.grants.length, 1);
});
