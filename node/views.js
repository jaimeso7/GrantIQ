import { statuses, weights } from './validation.js';
import { reviewFields } from './matching.js';
import { dispositions, status } from './service.js';
export const esc = (v) =>
  String(v ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  );
export const money = (v) =>
  v === null || v === undefined
    ? 'Unknown'
    : new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: 0,
      }).format(v);
const label = (k) =>
  ({ q: 'Search grants', min_score: 'Minimum fit score' })[k] ||
  k.replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase());
export const input = (key, value = '', type = 'text', extra = '') =>
  `<label>${esc(label(key))}<input name="${esc(key)}" type="${type}" value="${esc(value)}" ${extra}></label>`;
export const textarea = (key, value = '', rows = 4) =>
  `<label>${esc(label(key))}<textarea name="${esc(key)}" rows="${rows}">${esc(Array.isArray(value) ? value.join('\n') : value)}</textarea></label>`;
export const select = (key, value, options) =>
  `<label>${esc(label(key))}<select name="${esc(key)}">${options.map((v) => `<option value="${esc(v)}" ${String(v) === String(value) ? 'selected' : ''}>${esc(v || 'Any')}</option>`).join('')}</select></label>`;
export const csrf = (token) => `<input type="hidden" name="_csrf" value="${esc(token)}">`;
export const form = (url, token, content, button = 'Save') =>
  `<form method="post" action="${esc(url)}">${csrf(token)}${content}<button type="submit">${esc(button)}</button></form>`;
export function layout(title, body, { token = '', notice = '', auth = false } = {}) {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${esc(title)} · GrantIQ</title><link rel="stylesheet" href="/static/node.css"><script src="/static/node.js" defer></script></head><body><header><a class="brand" href="/">GrantIQ<span>Grant discovery & matching</span></a><nav aria-label="Main navigation"><a href="/">Discover</a><a href="/pipeline">My pipeline</a><a href="/sources">Data sources</a><a href="/research">Team research</a><a href="/settings">Organization profile</a><a href="/sprint-review">Project overview</a></nav>${auth ? form('/logout', token, '', 'Sign out') : ''}</header><main>${notice ? `<p class="notice" role="status">${esc(notice)}</p>` : ''}<h1>${esc(title)}</h1>${body}</main><footer>GrantIQ · Explainable fit scores guide research; verify eligibility and dates with official sources.</footer></body></html>`;
}
export function searchPanel(s, token) {
  const x = status(s);
  return `<section class="panel"><div class="heading"><h2>Recurring discovery</h2>${form('/refresh', token, '', 'Search now')}</div><p id="search-live" data-status>${esc(x.running ? 'Search running' : `${x.worker === 'available' ? 'Worker available' : 'Worker unavailable'} · ${s.schedule.enabled ? 'Every ' + s.schedule.interval_hours + ' hours' : 'Paused'}`)}</p><p>Last result: <strong>${esc(x.latest?.status || 'No searches yet')}</strong> · Next search: <time>${esc(s.schedule.enabled ? s.schedule.next_run_at : 'Paused')}</time></p><p class="muted">Searches run while the server and internet connection are available. A partial result is not complete coverage.</p></section>`;
}
export function card(g) {
  const r = g.record,
    a = g.assessment || {};
  return `<article class="panel"><div class="heading"><div><p class="eyebrow">${esc(r.funder_name)}</p><h2><a href="/grants/${g.id}">${esc(r.grant_title)}</a></h2></div><div class="score">${esc(a.fit_score ?? 0)}<small>/ 100 fit</small></div></div><p>${esc(r.description.slice(0, 400))}${r.description.length > 400 ? '…' : ''}</p><div class="tags"><span>${esc(a.eligibility_status)}</span><span>${esc(a.recommendation)}</span><span>${esc(a.confidence_score)}% data completeness</span><span>${esc(g.pipeline?.status || 'Discovered')}</span></div><p>Deadline: <strong>${esc(r.deadline || r.deadline_text || 'Unknown')}</strong> · Award: ${money(r.award_min)} – ${money(r.award_max)}</p>${g.staff_context ? `<p class="notice">${esc(g.staff_context.label)}: ${esc(g.staff_context.reason)}</p>` : ''}<a href="/grants/${g.id}">Review opportunity →</a></article>`;
}
export function dashboard(s, items, q, token) {
  return `<p class="lead">Find opportunities that fit your mission. Review evidence, then decide what to pursue.</p>${searchPanel(s, token)}<div class="stats"><div><strong>${s.grants.length}</strong> stored grants</div><div><strong>${s.grants.filter((g) => g.pipeline).length}</strong> saved to pipeline</div><div><strong>${items.length}</strong> matching filters</div></div><section class="panel"><form method="get" action="/"><div class="grid">${input('q', q.q, 'search')}${input('min_score', q.min_score, 'number', 'min="0" max="100"')}${select('eligibility', q.eligibility, ['', 'Eligible', 'Likely Eligible', 'Needs Review', 'Ineligible'])}${select('pipeline_status', q.pipeline_status, ['', ...statuses])}</div><details><summary>More filters</summary><div class="grid">${['funder', 'geography', 'population', 'category', 'source'].map((k) => input(k, q[k])).join('')}${input('amount_min', q.amount_min, 'number', 'min="0"')}${input('deadline', q.deadline, 'date')}</div><label class="check"><input type="checkbox" name="include_closed" value="1" ${q.include_closed ? 'checked' : ''}>Include closed and archived</label><label class="check"><input type="checkbox" name="include_staff_hidden" value="1" ${q.include_staff_hidden ? 'checked' : ''}>Include staff-excluded and deferred</label></details><button>Apply filters</button> <a href="/">Clear filters</a> · <a href="/export.csv?${esc(new URLSearchParams(q))}">Export filtered CSV</a></form></section>${items.length ? items.map(card).join('') : '<section class="panel"><h2>No opportunities match this view</h2><p>Check the source status, complete your profile, or broaden the filters. A new installation starts with no collected grants.</p></section>'}`;
}
export function pipeline(s, items, q, token) {
  return `<p class="lead">Track applications and team notes. Moving a grant does not submit an application.</p><section class="panel"><form method="get">${select('pipeline_status', q.pipeline_status, ['', ...statuses])}<button>Filter pipeline</button></form></section>${items.map(card).join('') || '<p>No saved opportunities yet. Open a grant and choose a pipeline stage.</p>'}`;
}
export function detail(g, token) {
  const r = g.record,
    a = g.assessment,
    p = g.pipeline || {};
  return `<p><a href="/">← Discover</a></p>${card(g)}<section class="panel"><h2>Source and evidence</h2><p><a href="${esc(r.source_url)}" target="_blank" rel="noopener noreferrer">Official source</a>${r.application_url ? ` · <a href="${esc(r.application_url)}" target="_blank" rel="noopener noreferrer">Application page</a>` : ''}</p><p>Last checked: ${esc(r.last_checked)} · Scoring mode: <strong>${esc(a.semantic_mode)}</strong></p><p>${esc(r.description)}</p><h3>Eligibility text</h3><p>${esc(r.eligibility_text || 'Not provided')}</p><p>Verification: ${esc(g.state)}</p><a href="/grants/${g.id}/verify">Verify source facts</a><ul>${a.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul></section><section class="panel"><h2>Why this score?</h2><table><thead><tr><th>Component</th><th>Points</th><th>Explanation</th></tr></thead><tbody>${a.components.map((c) => `<tr><td>${esc(c.label)}</td><td>${c.points}/${c.maximum}</td><td>${esc(c.explanation)}</td></tr>`).join('')}</tbody></table><h3>Eligibility checks</h3><ul>${a.eligibility_checks.map((c) => `<li><strong>${esc(c.outcome)}</strong> · ${esc(c.explanation)}</li>`).join('')}</ul></section><section class="panel"><h2>Team pipeline</h2>${form(`/grants/${g.id}/pipeline`, token, `<div class="grid">${select('status', p.status || 'Interested', statuses)}${input('assigned_to', p.assigned_to)}${input('requested_amount', p.requested_amount, 'number', 'min="0" step="0.01"')}${input('application_deadline', p.application_deadline, 'date')}${input('submission_date', p.submission_date, 'date')}</div>${textarea('notes', p.notes)}${textarea('final_result', p.final_result)}`, 'Save pipeline')}</section><section class="panel"><h2>Application requirements</h2><ul>${r.application_requirements.map((v) => `<li>${esc(v)}</li>`).join('') || '<li>Review official announcement.</li>'}</ul><p>${esc(r.contact_information)}</p><h3>Source history</h3><ul>${g.sources.map((v) => `<li><a href="${esc(v.source_url)}">${esc(v.source)}</a> · ${esc(v.last_checked)}</li>`).join('')}</ul><h3>Verification history</h3>${g.reviews.map((v) => `<p>${esc(v.action)} · ${esc(v.reviewed_by)} · ${esc(v.reviewed_at)} · ${esc(v.evidence_note)} <a href="${esc(v.evidence_url)}">Evidence</a></p>`).join('') || '<p>No staff verifications yet.</p>'}</section>`;
}
export function settings(p, token) {
  return `<p class="lead">These settings drive eligibility, scoring, and discovery. List one item per line.</p>${form(
    '/settings',
    token,
    `<section class="panel"><h2>Organization</h2><div class="grid">${['name', 'organization_type', 'ein', 'profile_source_url'].map((k) => input(k, p[k], k === 'profile_source_url' ? 'url' : 'text')).join('')}${input('annual_budget', p.annual_budget, 'number', 'min="0" step="0.01"')}</div>${textarea('mission', p.mission)}${textarea('description', p.description)}</section><section class="panel"><h2>Communities and programs</h2><div class="grid">${['service_locations', 'populations_served', 'programs', 'funding_interests'].map((k) => textarea(k, p[k])).join('')}</div></section><section class="panel"><h2>Funding and readiness</h2><div class="grid">${['minimum_desired_award', 'maximum_desired_award', 'minimum_days_to_apply'].map((k) => input(k, p[k], 'number', 'min="0" step="0.01"')).join('')}${input('readiness_thresholds', p.readiness_thresholds.join(', '))}${['matching_funds_available', 'has_fiscal_sponsor'].map((k) => select(k, p[k] === null ? 'unknown' : p[k] ? 'yes' : 'no', ['unknown', 'yes', 'no'])).join('')}</div><div class="grid">${['invited_by_funders', 'existing_funder_relationships', 'excluded_funders'].map((k) => textarea(k, p[k])).join('')}</div></section><section class="panel"><h2>Seven scoring weights (must total 100)</h2><div class="grid">${Object.keys(
      weights,
    )
      .map((k) => input('weight_' + k, p.weights[k], 'number', 'min="0" max="100" step="0.5"'))
      .join('')}</div></section>`,
    'Save profile and rescore',
  )}`;
}
export function sources(s, token) {
  return `${searchPanel(s, token)}<section class="panel"><h2>Search schedule</h2>${form('/sources/schedule', token, `<div class="grid">${select('interval_hours', s.schedule.interval_hours, [3, 6, 12, 24])}${select('enabled', s.schedule.enabled ? 'yes' : 'no', ['yes', 'no'])}</div>`, 'Save search schedule')}</section><section class="panel"><h2>Approved funding pages</h2><p>One public opportunity per page. Terms must be reviewed before enabling. Login controls and robots restrictions are respected.</p><a class="button" href="/sources/new">Add funding page</a>${s.sources.map((x) => `<p><a href="/sources/${x.id}/edit">${esc(x.name)}</a> · ${x.enabled ? 'Enabled' : 'Disabled'} · ${esc(x.url)}</p>`).join('')}</section><section class="panel"><h2>Refresh activity</h2>${
    [...s.runs]
      .reverse()
      .map(
        (r) =>
          `<details><summary>${esc(r.status)} · ${esc(r.started_at)} · ${r.added || 0} added / ${r.updated || 0} updated</summary><p>Found ${r.found || 0}; rejected ${r.rejected || 0}. Finished ${esc(r.finished_at || 'Still running')}.</p><ul>${(r.errors || []).map((e) => `<li>${esc(e)}</li>`).join('')}</ul></details>`,
      )
      .join('') || '<p>No searches yet.</p>'
  }</section>`;
}
export function sourceForm(s, token) {
  return `<p>Saving checks the public address; collection occurs during a search.</p>${form(s.id ? `/sources/${s.id}` : '/sources', token, `<section class="panel">${input('name', s.name, 'text', 'required maxlength="200"')}${input('url', s.url, 'url', 'required')}${input('reviewed_by', s.reviewed_by)}${input('terms_reference', s.terms_reference)}<div class="grid">${select('enabled', s.enabled ? 'yes' : 'no', ['no', 'yes'])}${select('terms_reviewed', s.terms_reviewed ? 'yes' : 'no', ['no', 'yes'])}</div>${textarea('selectors', JSON.stringify(s.selectors || {}, null, 2), 8)}<p>Optional JSON mapping: title, description, eligibility, deadline, award_min, award_max, application_url, applicant_types, geographic_restrictions, geography_scope, populations_served, categories, program_areas, status. Values are CSS selectors.</p></section>`, 'Save source')}`;
}
export function research(s, token) {
  return `<p class="lead">Staff preferences guide the shortlist separately from eligibility. A research review date is not an application deadline.</p><p>${s.prospects.length} research prospects · ${s.profile.excluded_funders.length} excluded funders. Edit exclusions in <a href="/settings">Organization profile</a>.</p>${s.prospects.map((p) => `<section class="panel"><h2>${esc(p.original.name)}</h2><p>${esc(p.original.staff_note)}</p><details><summary>Original research record</summary><pre>${esc(JSON.stringify(p.original, null, 2))}</pre></details>${form(`/research/${encodeURIComponent(p.id)}`, token, `<div class="grid">${select('disposition', p.disposition, dispositions)}${input('review_on', p.review_on, 'date')}</div>${textarea('team_notes', p.team_notes)}`, 'Save staff decision')}</section>`).join('') || '<section class="panel"><p>This public installation has no private research prospects. Import an authorized workspace or install private research configuration before first startup.</p></section>'}`;
}
export function verification(g, token) {
  return `<p>Confirm only facts you have checked against official evidence. Scores and eligibility verdicts cannot be directly edited.</p>${form(`/grants/${g.id}/verify`, token, `<section class="panel"><div class="grid">${input('reviewed_by', '', 'text', 'required')}${input('evidence_url', '', 'url', 'required')}${input('valid_until', '', 'date', 'required')}</div>${textarea('evidence_note', '', 3)}<p>Select each fact to verify. The new review replaces previous verified fields.</p>${reviewFields.map(([k, title, type]) => `<details><summary><label class="check"><input type="checkbox" name="fields" value="${k}">${esc(title)}</label></summary>${type === 'list' || type === 'text' ? textarea(k, g.record[k]) : type === 'bool' ? select(k, g.record[k] === null ? 'unknown' : g.record[k] ? 'yes' : 'no', ['unknown', 'yes', 'no']) : type === 'scope' ? select(k, g.record[k], ['unknown', 'local', 'state', 'regional', 'national']) : type === 'status' ? select(k, g.record[k], ['unknown', 'posted', 'forecasted', 'closed', 'archived']) : input(k, g.record[k], type === 'number' ? 'number' : type === 'date' ? 'date' : type === 'url' ? 'url' : 'text', type === 'number' ? 'min="0" step="0.01"' : '')}</details>`).join('')}</section>`, 'Save verified facts')}${form(`/grants/${g.id}/verify/withdraw`, token, input('reviewed_by', '', 'text', 'required'), 'Withdraw current verification')}`;
}
