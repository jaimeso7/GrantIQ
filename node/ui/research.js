import { dispositions } from '../service.js';
import { esc, input, textarea, select, form } from './html.js';

export function research(s, token) {
  return /* HTML */ `<p class="lead">
      Staff preferences guide the shortlist separately from eligibility. A research review date is
      not an application deadline.
    </p>
    <p>
      ${s.prospects.length} research prospects · ${s.profile.excluded_funders.length} excluded
      funders. Edit exclusions in <a href="/settings">Organization profile</a>.
    </p>
    ${s.prospects
      .map(
        (p) =>
          /* HTML */ `<section class="panel">
            <h2>${esc(p.original.name)}</h2>
            <p>${esc(p.original.staff_note)}</p>
            <details>
              <summary>Original research record</summary>
              <pre>${esc(JSON.stringify(p.original, null, 2))}</pre>
            </details>
            ${form(
              `/research/${encodeURIComponent(p.id)}`,
              token,
              /* HTML */ `<div class="grid">
                  ${select('disposition', p.disposition, dispositions)}${input(
                    'review_on',
                    p.review_on,
                    'date',
                  )}
                </div>
                ${textarea('team_notes', p.team_notes)}`,
              'Save staff decision',
            )}
          </section>`,
      )
      .join('') ||
    '<section class="panel"><p>This public installation has no private research prospects. Import an authorized workspace or install private research configuration before first startup.</p></section>'}`;
}
