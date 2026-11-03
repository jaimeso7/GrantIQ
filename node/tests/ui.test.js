import { test } from 'node:test';
import assert from 'node:assert/strict';
import { overviewStats } from '../ui/discovery.js';
import { record } from './helpers.js';

test('overview totals distinguish strong eligible grants, upcoming dates and recent discoveries', () => {
  const clock = Date.parse('2026-10-25T12:00:00Z');
  const grant = (status, eligibility, deadline, discovered) => ({
    record: record({ grant_status: status, deadline }),
    assessment: { fit_score: 95, eligibility_status: eligibility },
    date_discovered: discovered,
  });
  const grants = [
    grant('posted', 'Eligible', '2026-11-01', '2026-10-24T12:00:00Z'),
    grant('posted', 'Ineligible', '2026-11-02', '2026-09-01T12:00:00Z'),
    grant('closed', 'Eligible', '2026-10-24', '2026-09-01T12:00:00Z'),
    grant('forecasted', 'Needs Review', null, '2026-10-26T12:00:00Z'),
  ];
  assert.deepEqual(
    overviewStats(grants, clock).map(([, count]) => count),
    [3, 1, 2, 1],
  );
});
