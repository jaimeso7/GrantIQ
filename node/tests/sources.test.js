import { test } from 'node:test';
import assert from 'node:assert/strict';
import { federal, normalizeFederal, parseAmount, parseDate, approvedPage } from '../sources.js';
import { isPublic, publicAddress } from '../network.js';
const detail = (id) => ({
  id,
  opportunityTitle: 'Real title',
  synopsis: {
    synopsisDesc: '<p>Health</p>',
    agencyDetails: { agencyName: 'Agency' },
    awardFloor: 0,
    awardCeiling: 10000,
    costSharing: false,
  },
});
test('federal adapter preserves zero/false and does not invent geography or award estimate', () => {
  const g = normalizeFederal({ ...detail(1), _search: { oppStatus: 'posted' } });
  assert.equal(g.award_min, 0);
  assert.equal(g.matching_funds_required, false);
  assert.equal(g.geography_scope, 'unknown');
  assert.equal(g.estimated_award, null);
  assert.equal(g.funder_name, 'Agency');
  assert.equal(g.description, 'Health');
});
test('round robin paginates and reports bounded cap', async () => {
  const stats = { found: 0, rejected: 0, truncated: false },
    errors = [],
    terms = [];
  const post = async (endpoint, payload) => {
    if (endpoint === 'fetchOpportunity') return detail(payload.opportunityId);
    terms.push(payload.keyword);
    return { hitCount: 10, oppHits: [{ id: terms.length, oppStatus: 'posted' }] };
  };
  const items = [];
  for await (const g of federal(['vision', 'health'], 2, { stats, errors, post })) items.push(g);
  assert.deepEqual(terms, ['vision', 'health']);
  assert.equal(items.length, 2);
  assert.equal(stats.truncated, true);
  assert.match(errors[0], /bounded subset/);
});
test('malformed detail never replaces existing rich record', async () => {
  const errors = [],
    stats = { found: 0, rejected: 0, truncated: false };
  const post = async (endpoint) =>
    endpoint === 'search2' ? { hitCount: 1, oppHits: [{ id: 1 }] } : detail(2);
  const items = [];
  for await (const g of federal(['vision'], 2, { post, errors, stats })) items.push(g);
  assert.equal(items.length, 0);
  assert.equal(stats.rejected, 1);
  assert.match(errors[0], /mismatch/);
});
test('SSRF protections reject private, mapped private and mixed DNS', async () => {
  for (const ip of [
    '127.0.0.1',
    '10.0.0.1',
    '169.254.169.254',
    '::1',
    '::ffff:127.0.0.1',
    'fe80::1',
  ])
    assert.equal(isPublic(ip), false);
  assert.equal(isPublic('8.8.8.8'), true);
  await assert.rejects(
    () =>
      publicAddress('http://example.org', async () => [
        { address: '8.8.8.8', family: 4 },
        { address: '10.0.0.1', family: 4 },
      ]),
    /public/,
  );
  await assert.rejects(() => publicAddress('http://example.org:22'), /ports/);
});
test('numeric and date normalization rejects malformed values', () => {
  assert.equal(parseAmount('NaN'), null);
  assert.equal(parseAmount(false), null);
  assert.equal(parseAmount('$12,000'), 12000);
  assert.equal(parseDate('2026-02-30'), null);
});
test('approved pages obey robots and preserve unknown facts', async () => {
  const source = {
    id: 'one',
    name: 'Example',
    url: 'https://example.org/grant',
    enabled: true,
    terms_reviewed: true,
    selectors: { title: 'h1' },
  };
  const fetch = async (url) =>
    url.endsWith('/robots.txt')
      ? { text: 'User-agent: *\nAllow: /' }
      : {
          text: '<h1>Community grant</h1><main>Health programs</main>',
          headers: { 'content-type': 'text/html' },
        };
  const g = await approvedPage(source, { fetch, wait: async () => {} });
  assert.equal(g.grant_title, 'Community grant');
  assert.equal(g.geography_scope, 'unknown');
  assert.equal(g.award_max, null);
  await assert.rejects(
    () =>
      approvedPage(source, {
        fetch: async () => ({ text: 'User-agent: *\nDisallow: /' }),
        wait: async () => {},
      }),
    /Robots/,
  );
  await assert.rejects(() => approvedPage({ ...source, terms_reviewed: false }), /terms review/);
});
