import { test } from 'node:test';
import assert from 'node:assert/strict';
import { profile, record } from './helpers.js';
import { score, geography, revision, effective, staffContext } from '../matching.js';
import { profileSchema } from '../validation.js';
test('eligibility overrides strong semantic similarity', () => {
  const a = score(record({ applicant_types: ['State governments only'] }), profile(), {
    similarity: 0.99,
  });
  assert.equal(a.fit_score, 0);
  assert.equal(a.eligibility_status, 'Ineligible');
});
test('county geography does not infer overlap from shared state', () => {
  assert.equal(
    geography(record({ geographic_restrictions: ['Orange County, Florida'] }), profile()).outcome,
    'fail',
  );
  assert.equal(
    geography(record({ geographic_restrictions: ['Duval County, Florida'] }), profile()).fraction,
    1,
  );
});
test('explicit exclusion overrides national geography', () =>
  assert.equal(
    geography(
      record({
        geography_scope: 'national',
        eligibility_text: 'Available nationally excluding Florida',
      }),
      profile(),
    ).outcome,
    'fail',
  ));
test('unknown geography stays needs-review; fallback capped', () => {
  const a = score(record({ geographic_restrictions: [], geography_scope: 'unknown' }), profile());
  assert.equal(a.eligibility_status, 'Needs Review');
  assert.equal(a.semantic_mode, 'keyword_fallback');
  assert.ok(a.components.find((c) => c.key === 'mission').points <= 10.5);
});
test('past giving requires attributed recipient details', () => {
  const g = record({
    past_giving: [
      { recipient: 'Charity', similarity: 1, source_url: 'https://example.org/evidence' },
    ],
  });
  assert.equal(score(g, profile()).components.find((c) => c.key === 'past_giving').points, 0);
});
test('expired and forecast dates have distinct eligibility', () => {
  assert.equal(
    score(record({ deadline: '2000-01-01' }), profile()).eligibility_status,
    'Ineligible',
  );
  assert.equal(
    score(record({ grant_status: 'forecasted' }), profile()).eligibility_status,
    'Needs Review',
  );
});
test('profile rejects contradictory financial limits and weights', () => {
  assert.throws(() => profileSchema.parse({ ...profile(), maximum_desired_award: 1 }));
  assert.throws(() =>
    profileSchema.parse({ ...profile(), weights: { ...profile().weights, mission: 99 } }),
  );
});
test('recheck alone preserves evidence; changed facts and expiry invalidate', () => {
  const g = record(),
    item = {
      record: g,
      reviews: [
        {
          action: 'verified',
          facts: { award_max: 20000 },
          source_revision: revision(g),
          valid_until: '2099-01-01',
          reviewed_by: 'Reviewer',
          evidence_url: 'https://example.org/evidence',
        },
      ],
    };
  assert.equal(effective(item).record.award_max, 20000);
  item.record = { ...g, last_checked: '2090-01-01', warnings: ['new warning'] };
  assert.equal(effective(item).state, 'current');
  item.record = { ...g, description: 'Changed criteria' };
  assert.equal(effective(item).state, 'source_changed');
  item.record = g;
  item.reviews[0].valid_until = '2000-01-01';
  assert.equal(effective(item).state, 'expired');
});
test('staff exclusions remain preferences; deferred prospects hidden', () => {
  const p = profile(),
    g = { record: record() };
  p.excluded_funders = ['The Example Foundation Inc'];
  assert.equal(staffContext(g, { profile: p, prospects: [] }).hidden, true);
  p.excluded_funders = [];
  assert.equal(
    staffContext(g, {
      profile: p,
      prospects: [
        {
          original: { name: 'Example Foundation' },
          disposition: 'Pursue',
          review_on: '2099-01-01',
        },
      ],
    }).label,
    'Deferred by staff',
  );
});
