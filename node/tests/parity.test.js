import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { score } from '../matching.js';
for (const f of JSON.parse(
  fs.readFileSync(new URL('./fixtures/python-parity.json', import.meta.url)),
))
  test(f.name, () => {
    const a = score(f.record, f.profile, { day: '2026-10-21', similarity: 0.8, mode: 'fixture' });
    assert.equal(a.eligibility_status, f.eligibility_status);
    assert.equal(a.fit_score, f.fit_score);
    assert.equal(a.confidence_score, f.confidence_score);
    assert.deepEqual(Object.fromEntries(a.components.map((c) => [c.key, c.points])), f.points);
  });
