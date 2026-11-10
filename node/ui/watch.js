import { esc, form, select, textarea, input } from './html.js';
import { watchReport } from '../watch-report.js';
import { views } from '../service.js';

export function watch(s, token) {
  const report = watchReport(views(s), s.grantUpdates);
  const cards = (list) =>
    list
      .map(
        (g) =>
          `<li><a href="/grants/${g.id}">${esc(g.record.grant_title)}</a> â€” ${esc(g.record.funder_name)} Â· ${g.assessment.fit_score}/100 Â· ${esc(g.record.deadline || 'Deadline not verified')}<br>${esc(g.assessment.application_path?.next)}</li>`,
      )
      .join('') || '<li>No opportunities meet this sectionâ€™s verification criteria.</li>';
  return `<p class="lead">Foundation discovery and grant watch</p>
    <p><a class="button" href="#foundation-inbox">Review foundation leads</a> · <a href="/sources">Search settings and activity</a></p>
    <p>First seen means newly discovered by GrantIQ, not newly announced. Search results and historical Form 990/990-PF records require official-source verification.</p>
    ${[
      ['A Â· Actionable priorities', report.actionable],
      ['B Â· Confirmed upcoming openings', report.upcoming],
      ['C Â· Invitation-only prospects with a contact to investigate', report.cultivate],
      ['E Â· Verified deadlines in the next 60 days', report.deadlines],
    ]
      .map(
        ([name, list]) =>
          `<section class="panel"><h2>${name}</h2><ul>${cards(list)}</ul></section>`,
      )
      .join('')}
    <section class="panel"><h2>D Â· Important source updates</h2><ul>${report.updates.map((u) => `<li><a href="/grants/${u.grant_id}">${esc(u.title)}</a> Â· ${esc(u.at)}<p>${esc(u.summary)}</p></li>`).join('') || '<li>No recorded material changes.</li>'}</ul></section>
    <section class="panel"><h2>E · Verified deadlines in the next 60 days</h2><ul>${cards(report.deadlines)}</ul></section>
    <section class="panel" id="foundation-inbox"><h2>Foundation research inbox</h2>
    <p>These leads have no grant fit score until an actual opportunity is recorded. Filing data does not establish an open application or geographic eligibility. Source: <a href="https://projects.propublica.org/nonprofits/api/">ProPublica Nonprofit Explorer / IRS</a>. Web discovery requires a configured search API. Candid is not connected yet.</p>
    <p>${(s.discoveryLeads || []).length} saved leads. Showing the latest 100 active leads. Dismissed and converted leads remain saved.</p>
    ${
      (s.discoveryLeads || [])
        .filter((l) => !['Dismissed', 'Converted'].includes(l.disposition))
        .slice(-100)
        .reverse()
        .map(
          (l) => `<details class="panel"><summary>${esc(l.title)} Â· ${esc(l.disposition)}</summary>
      <p>${esc(l.kind)} Â· ${esc(l.provider)} Â· First seen ${esc(l.first_seen)}</p><p>${esc(l.summary)}</p>
      <p><a href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">Research source</a> Â· <a href="/sources/new">Add verified official funding page for monitoring</a></p>
      ${form(
        '/research/leads/' + l.id + '/opportunity',
        token,
        '<p>After finding the official program, create an unverified opportunity and record its evidence. This does not mark the grant eligible or open.</p>' +
          input('funder_name', '', 'text', 'required maxlength="200"') +
          input('grant_title', '', 'text', 'required maxlength="500"') +
          input('official_url', '', 'url', 'required'),
        'Create opportunity to verify',
      )}
      ${form('/research/leads/' + l.id, token, select('disposition', l.disposition, ['Verify', 'Cultivate', 'Monitor', 'Dismissed', 'Converted']) + textarea('notes', l.notes), 'Save lead review')}
    </details>`,
        )
        .join('') || '<p>No active research leads yet. Run a search from Data sources.</p>'
    }</section>`;
}
