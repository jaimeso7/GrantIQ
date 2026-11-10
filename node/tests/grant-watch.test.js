import { test } from 'node:test';
import assert from 'node:assert/strict';
import { profile, record, seed, tempStore } from './helpers.js';
import { watchScore, rubric } from '../grant-watch.js';
import { foundationLeads, foundationQueries, saveLead } from '../foundation-discovery.js';
import { recordUpdate, watchReport } from '../watch-report.js';
import { createDiscovery } from '../discovery.js';

test('grant-watch rubric totals 100 and disqualifiers override every component', () => {
  assert.deepEqual(
    Object.values(rubric).map((v) => v[1]),
    [25, 20, 15, 15, 10, 10, 5],
  );
  const a = watchScore(record({ applicant_types: ['State governments only'] }), profile(), {
    similarity: 1,
  });
  assert.equal(a.fit_score, 0);
  assert.equal(a.recommendation, 'INELIGIBLE');
});
test('unknown awards, expenses, eligibility and opening remain unverified', () => {
  const a = watchScore(
    record({
      award_min: null,
      award_max: null,
      program_areas: [],
      categories: [],
      grant_status: 'unknown',
      geographic_restrictions: [],
      geography_scope: 'unknown',
    }),
    profile(),
  );
  for (const key of ['purpose', 'value', 'accessibility', 'timing'])
    assert.equal(a.components.find((c) => c.key === key).points, 0);
  assert.equal(a.provisional, true);
  assert.match(a.application_path.effort, /Not verified/);
  assert.ok(Array.isArray(a.match_explanation));
});
test('directory leads remain historical prospects and national queries are included', async () => {
  const calls = [],
    errors = [];
  const fetch = async (url) => {
    calls.push(url);
    return {
      text: JSON.stringify({
        organizations: [{ ein: 123, name: 'Example Foundation', city: 'Boston', state: 'MA' }],
      }),
    };
  };
  const leads = [];
  for await (const l of foundationLeads({ foundationDiscovery: true }, 20, { errors, fetch }))
    leads.push(l);
  assert.equal(leads.length, 1);
  assert.match(leads[0].summary, /not verified/);
  assert.equal(new URL(calls[0]).searchParams.has('state[id]'), false);
  assert.equal(leads[0].grant_status, undefined);
  assert.ok(foundationQueries(32).some((q) => q.includes('United States')));
});
test('web discovery is disabled without a key and bounded with an authorized key', async () => {
  let calls = 0;
  const fetch = async (_url, options) => {
    calls++;
    assert.equal(options.headers['X-Subscription-Token'], 'test-key');
    return {
      text: JSON.stringify({
        web: {
          results: [
            { title: 'Program', url: 'https://example.org/grant' },
            { url: 'javascript:alert(1)' },
          ],
        },
      }),
    };
  };
  for await (const _ of foundationLeads({}, 0, { errors: [], fetch })) assert.fail();
  assert.equal(calls, 0);
  const leads = [];
  for await (const l of foundationLeads({ webSearchKey: 'test-key' }, 0, {
    errors: [],
    fetch,
    pause: async () => {},
  }))
    leads.push(l);
  assert.equal(calls, 3);
  assert.equal(leads.length, 3);
});
test('research deduplicates tracking URLs, preserves decisions and respects exclusions', () => {
  const s = seed();
  const l = {
    title: 'Example Foundation',
    url: 'https://example.org/grant?utm_source=search',
    summary: 'Snippet',
  };
  assert.equal(saveLead(s, l), true);
  s.discoveryLeads[0].disposition = 'Dismissed';
  assert.equal(
    saveLead(s, { ...l, url: 'https://example.org/grant', summary: 'Different snippet' }),
    false,
  );
  assert.equal(s.discoveryLeads[0].disposition, 'Dismissed');
  s.profile.excluded_funders = ['Another Foundation'];
  assert.equal(
    saveLead(s, { ...l, title: 'Another Foundation', url: 'https://another.org' }),
    false,
  );
});
test('poll timestamps do not create material updates; changed cycles do', () => {
  const s = seed(),
    previous = record();
  const g = { id: 1, record: { ...previous, last_checked: '2099-01-01' } };
  recordUpdate(s, g, previous);
  assert.equal(s.grantUpdates, undefined);
  g.record.deadline = '2099-11-01';
  recordUpdate(s, g, previous);
  assert.equal(s.grantUpdates.length, 1);
  recordUpdate(s, g, g.record);
  assert.equal(s.grantUpdates.length, 1);
});
test('watch report excludes provisional, closed and staff-hidden opportunities from actionable section', () => {
  const g = {
    id: 1,
    record: record({ deadline: '2099-05-20' }),
    assessment: { fit_score: 90, provisional: false, eligibility_status: 'Eligible' },
  };
  const report = watchReport(
    [
      g,
      { ...g, id: 2, assessment: { ...g.assessment, provisional: true } },
      { ...g, id: 3, record: { ...g.record, grant_status: 'closed' } },
      { ...g, id: 4, staff_context: { hidden: true } },
    ],
    [],
    '2099-05-01',
  );
  assert.deepEqual(
    report.actionable.map((g) => g.id),
    [1],
  );
  assert.deepEqual(
    report.deadlines.map((g) => g.id),
    [1],
  );
});
test('recurring discovery saves independent foundation leads once across repeated runs', async (t) => {
  const { store, config } = await tempStore(t);
  const fetchLeads = async function* () {
    yield { title: 'New Foundation', url: 'https://example.org/foundation' };
  };
  const discovery = createDiscovery(store, config, {
    fetchLeads,
    fetchFederal: async function* () {},
  });
  await discovery.run();
  await discovery.run();
  const s = await store.read();
  assert.equal(s.discoveryLeads.length, 1);
  assert.equal(s.runs[0].foundation_leads, 1);
  assert.equal(s.runs[1].foundation_leads || 0, 0);
  assert.equal(s.grants.length, 0);
});
