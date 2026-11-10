import { daysUntil } from './matching.js';
import { today, now } from './store.js';

// Only substantive opportunity fields trigger updates. Poll timestamps, HTML
// formatting and search-snippet changes are deliberately not announcements.
export function materialFacts(r) {
  return JSON.stringify([
    r.grant_status,
    r.deadline,
    r.open_date,
    r.application_url,
    r.award_min,
    r.award_max,
    r.estimated_award,
    r.eligibility_text,
    r.geographic_restrictions,
    r.application_requirements,
    r.invitation_only,
    r.loi_required,
  ]);
}
export function recordUpdate(s, g, previous) {
  if (!previous || materialFacts(previous) === materialFacts(g.record)) return;
  s.grantUpdates ||= [];
  s.grantUpdates.push({
    grant_id: g.id,
    at: now(),
    title: g.record.grant_title,
    previous_status: previous.grant_status,
    status: g.record.grant_status,
    previous_deadline: previous.deadline,
    deadline: g.record.deadline,
    summary:
      'Source facts changed. Review the current cycle, eligibility, amount and application requirements.',
  });
  s.grantUpdates = s.grantUpdates.slice(-500);
}
export function watchReport(items, updates = [], day = today()) {
  const visible = items.filter((g) => !g.staff_context?.hidden && !g.record.is_demo);
  const eligible = visible.filter((g) => g.assessment?.eligibility_status !== 'Ineligible');
  const actionable = eligible.filter(
    (g) =>
      g.assessment?.fit_score >= 75 &&
      !g.assessment.provisional &&
      g.record.grant_status === 'posted' &&
      (!g.record.open_date || g.record.open_date <= day) &&
      (g.record.deadline
        ? daysUntil(g.record.deadline, day) >= 0
        : /rolling|ongoing|no deadline/i.test(g.record.deadline_text)),
  );
  const upcoming = eligible.filter(
    (g) => g.record.grant_status === 'forecasted' && g.record.open_date > day,
  );
  const cultivate = eligible.filter(
    (g) => g.record.invitation_only === true && !!g.record.contact_information,
  );
  const deadlines = eligible
    .filter(
      (g) =>
        g.record.grant_status === 'posted' &&
        !g.assessment.provisional &&
        g.record.deadline &&
        daysUntil(g.record.deadline, day) >= 0 &&
        daysUntil(g.record.deadline, day) <= 60,
    )
    .sort((a, b) => a.record.deadline.localeCompare(b.record.deadline));
  return {
    actionable,
    upcoming,
    cultivate,
    deadlines,
    updates: updates
      .filter((u) => visible.some((g) => g.id === u.grant_id))
      .slice(-30)
      .reverse(),
  };
}
