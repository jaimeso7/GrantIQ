import { statuses } from '../validation.js';
import { status } from '../service.js';
import { esc, money, input, textarea, select, form } from './html.js';
import { icon } from './icons.js';

function dateText(value, includeTime = false) {
  if (!value) return 'Not available';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return value;
  return (
    new Intl.DateTimeFormat('en-US', {
      dateStyle: 'medium',
      ...(includeTime ? { timeStyle: 'short' } : {}),
      timeZone: 'UTC',
    }).format(date) + (includeTime ? ' UTC' : '')
  );
}

function award(record) {
  const { award_min: min, award_max: max, estimated_award: estimate } = record;
  if (min != null && max != null) return min === max ? money(min) : `${money(min)}–${money(max)}`;
  if (max != null) return `Up to ${money(max)}`;
  if (min != null) return `From ${money(min)}`;
  return estimate != null ? `Est. ${money(estimate)}` : 'Amount unknown';
}

function badge(label = 'Needs Review') {
  const className = label.toLowerCase().replace(/[^a-z0-9]+/g, '-');
  return `<span class="badge badge-${className}">${esc(label)}</span>`;
}

/** Count real stored records, independently of dashboard filters. No demo totals. */
export function overviewStats(grants, clock = Date.now()) {
  const active = grants.filter((g) => ['posted', 'forecasted'].includes(g.record.grant_status));
  const today = new Date(clock).toISOString().slice(0, 10);
  const cutoff = new Date(clock + 30 * 86400000).toISOString().slice(0, 10);
  return [
    ['Active opportunities', active.length, 'Posted and forecasted records', 'database'],
    [
      'Strong matches',
      active.filter(
        (g) =>
          g.assessment?.fit_score >= 80 &&
          ['Eligible', 'Likely Eligible'].includes(g.assessment?.eligibility_status),
      ).length,
      'Fit score 80+ · eligibility considered',
      'spark',
    ],
    [
      'Upcoming deadlines',
      active.filter((g) => g.record.deadline >= today && g.record.deadline <= cutoff).length,
      'Due within the next 30 days',
      'calendar',
    ],
    [
      'New opportunities',
      grants.filter(
        (g) =>
          Date.parse(g.date_discovered) >= clock - 7 * 86400000 &&
          Date.parse(g.date_discovered) <= clock,
      ).length,
      'Discovered in the last 7 days',
      'grid',
    ],
  ];
}

export function searchPanel(workspace, token) {
  const current = status(workspace);
  const schedule = workspace.schedule;
  const activity = current.running ? 'Search running' : `Worker ${current.worker}`;
  return /* HTML */ ` <section class="search-monitor" aria-label="Recurring grant discovery">
    <div class="monitor-heading heading">
      <div>
        <p class="eyebrow">ALWAYS KNOW WHERE YOUR SEARCH STANDS</p>
        <h2>Recurring grant discovery</h2>
      </div>
      ${form('/refresh', token, '', current.running ? 'Search running' : 'Search now')}
    </div>
    <p class="search-status" data-status role="status">
      ${esc(activity)} · ${schedule.enabled ? `Every ${schedule.interval_hours} hours` : 'Paused'}
    </p>
    <div class="monitor-grid">
      <div>
        <span class="monitor-label">Last search result</span
        ><strong class="monitor-value">${esc(current.latest?.status || 'No searches yet')}</strong>
      </div>
      <div>
        <span class="monitor-label">Next scheduled search</span
        ><strong class="monitor-value" data-next-search
          >${esc(schedule.enabled ? dateText(schedule.next_run_at, true) : 'Paused')}</strong
        >
      </div>
      <div>
        <span class="monitor-label">Search frequency</span
        ><strong class="monitor-value" data-search-frequency
          >${schedule.enabled ? `Every ${schedule.interval_hours} hours` : 'Paused'}</strong
        ><a href="/sources#search-schedule">Manage schedule →</a>
      </div>
    </div>
    <p class="small muted">
      Searches run while the server and internet connection are available. Partial results do not
      mean complete coverage.
    </p>
  </section>`;
}

export function card(grant) {
  const record = grant.record;
  const assessment = grant.assessment || {};
  const reason =
    assessment.match_explanation?.[0] ||
    record.description.slice(0, 220) ||
    'Review the official source to understand this opportunity.';
  return /* HTML */ ` <article class="grant-card">
    <div
      class="fit-block ${assessment.eligibility_status === 'Ineligible' ? 'fit-block-muted' : ''}"
    >
      <span class="fit-value">${esc(assessment.fit_score ?? 0)}</span
      ><span class="fit-caption">FIT SCORE</span>
    </div>
    <div class="grant-content">
      <div class="grant-topline">
        <span class="eyebrow">${esc(record.funder_name)}</span>
        <div class="badge-group">
          ${badge(assessment.recommendation)}${record.grant_status === 'forecasted'
            ? badge('Forecasted')
            : ''}${grant.pipeline ? badge(grant.pipeline.status) : ''}
        </div>
      </div>
      <h3><a href="/grants/${grant.id}">${esc(record.grant_title)}</a></h3>
      <div class="grant-facts">
        <span class="grant-amount">${award(record)}</span
        ><span
          >${icon('calendar')}
          ${esc(
            record.deadline
              ? `Due ${dateText(record.deadline)}`
              : record.deadline_text || 'Deadline unknown',
          )}</span
        ><span
          >${icon('pin')}
          ${esc(record.geographic_restrictions.join(', ') || 'Location unknown')}</span
        >
      </div>
      <p class="match-reason"><span class="reason-icon">${icon('spark')}</span>${esc(reason)}</p>
      <div class="grant-bottom">
        <div class="grant-attributes">
          ${badge(assessment.eligibility_status)}<span class="confidence"
            >${esc(assessment.confidence_score ?? 0)}% data completeness</span
          >
        </div>
        <a class="text-link" href="/grants/${grant.id}">View opportunity ${icon('arrow')}</a>
      </div>
      ${assessment.warnings?.length
        ? `<p class="card-concern">${icon('info')} ${esc(assessment.warnings[0])}</p>`
        : ''}
      ${grant.staff_context
        ? `<p class="card-concern"><strong>Staff decision: ${esc(grant.staff_context.label)}.</strong> ${esc(grant.staff_context.reason)}</p>`
        : ''}
      <div class="grant-source">
        ${esc(record.source)} · Checked ${esc(dateText(record.last_checked))}
      </div>
    </div>
  </article>`;
}

function filters(query) {
  const expanded = [
    'funder',
    'geography',
    'population',
    'category',
    'source',
    'pipeline_status',
    'amount_min',
    'deadline',
    'include_closed',
    'include_staff_hidden',
  ].some((key) => query[key]);
  return /* HTML */ ` <form action="/" method="get" class="filter-panel">
    <div class="primary-filters">
      <label class="search-field"
        ><span class="sr-only">Search grants</span>${icon('search')}<input
          type="search"
          name="q"
          placeholder="Search grants, funders, or keywords…"
          value="${esc(query.q)}"
      /></label>
      <div class="compact-field">
        ${input(
          'min_score',
          query.min_score,
          'number',
          'min="0" max="100" placeholder="Any score"',
        )}
      </div>
      <div class="compact-field">
        ${select('eligibility', query.eligibility, [
          '',
          'Eligible',
          'Likely Eligible',
          'Needs Review',
          'Ineligible',
        ])}
      </div>
      <button class="button button-primary button-search">Search grants</button>
    </div>
    <details class="advanced-filters" ${expanded ? 'open' : ''}>
      <summary>${icon('filter')} More filters</summary>
      <div class="grid">
        ${['funder', 'geography', 'population', 'category', 'source']
          .map((key) => input(key, query[key]))
          .join('')}${select('pipeline_status', query.pipeline_status, ['', ...statuses])}${input(
          'amount_min',
          query.amount_min,
          'number',
          'min="0"',
        )}${input('deadline', query.deadline, 'date')}
      </div>
      <label class="check"
        ><input
          type="checkbox"
          name="include_closed"
          value="1"
          ${query.include_closed ? 'checked' : ''}
        />Include closed and archived</label
      >
      <label class="check"
        ><input
          type="checkbox"
          name="include_staff_hidden"
          value="1"
          ${query.include_staff_hidden ? 'checked' : ''}
        />Include staff-excluded and deferred</label
      >
      <button class="button button-secondary">Apply filters</button>
    </details>
  </form>`;
}

export function dashboard(workspace, items, query, token) {
  const stats = overviewStats(workspace.grants)
    .map(
      ([name, count, description, glyph]) =>
        /* HTML */ ` <article class="stat-card">
          <div class="stat-top">
            <span>${name}</span><span class="stat-icon">${icon(glyph)}</span>
          </div>
          <strong>${count}</strong><small>${description}</small>
        </article>`,
    )
    .join('');
  return /* HTML */ ` <section class="page-heading">
      <div>
        <p class="eyebrow teal">YOUR NEXT OPPORTUNITY STARTS HERE</p>
        <h1>Funding for your mission.</h1>
        <p class="lede">
          Find the grants most likely to fund your work. Understand the fit. Focus your effort.
        </p>
      </div>
    </section>
    ${searchPanel(workspace, token)}
    <section class="stats-grid" aria-label="Grant database overview">${stats}</section>
    <section class="opportunity-section" aria-labelledby="opportunities-heading">
      <div class="section-heading">
        <div>
          <h2 id="opportunities-heading">
            Discover opportunities <span class="count-pill">${items.length}</span>
          </h2>
          <p>Ranked by mission fit, with the context you need to decide.</p>
        </div>
        <a
          class="button button-secondary button-small"
          href="/export.csv?${esc(new URLSearchParams(query))}"
          >${icon('download')} Export CSV</a
        >
      </div>
      ${filters(query)}
      <div class="results-meta">
        <span>${items.length} opportunities · <a href="/">Clear filters</a></span
        ><span>Sorted by <strong>highest fit score</strong> ↓</span>
      </div>
      <div class="grant-list">
        ${items.length
          ? items.map(card).join('')
          : '<div class="empty-state"><h2>Your next opportunity is out there.</h2><p>Complete your profile and run a search, or broaden your filters.</p><a class="button button-secondary" href="/settings">Organization profile</a></div>'}
      </div>
    </section>
    <div class="data-note">
      ${icon('info')}
      <p>
        <strong>Fit is a starting point, not an award prediction.</strong> Data completeness
        measures available information. Review eligibility and source details before applying.
      </p>
    </div>`;
}

/** One tracking form is shared by detail pages and inline pipeline editors. */
export function pipelineForm(grant, token) {
  const saved = grant.pipeline || {};
  return form(
    `/grants/${grant.id}/pipeline`,
    token,
    /* HTML */ `
      <div class="grid">
        ${select('status', saved.status || 'Discovered', statuses)}${input(
          'assigned_to',
          saved.assigned_to,
        )}${input(
          'requested_amount',
          saved.requested_amount,
          'number',
          'min="0" step="0.01"',
        )}${input('application_deadline', saved.application_deadline, 'date')}${input(
          'submission_date',
          saved.submission_date,
          'date',
        )}
      </div>
      ${textarea('notes', saved.notes)}${textarea('final_result', saved.final_result)}
    `,
    'Save pipeline',
  );
}

export function pipeline(workspace, items, query, token) {
  const counters = statuses
    .map(
      (stage) =>
        `<a href="#status-${stage.toLowerCase()}" class="pipeline-stat"><strong>${items.filter((g) => g.pipeline.status === stage).length}</strong><span>${stage}</span></a>`,
    )
    .join('');
  const stages = statuses
    .map((stage) => {
      const grants = items.filter((g) => g.pipeline.status === stage);
      const cards = grants
        .map(
          (grant) =>
            /* HTML */ ` <article class="pipeline-card">
              <div class="pipeline-card-main">
                <span class="eyebrow">${esc(grant.record.funder_name)}</span>
                <h3><a href="/grants/${grant.id}">${esc(grant.record.grant_title)}</a></h3>
                <div class="pipeline-metadata">
                  <span><strong>${esc(grant.assessment?.fit_score ?? 0)}</strong> fit score</span
                  ><span>${award(grant.record)}</span
                  ><span
                    >Assigned to
                    <strong>${esc(grant.pipeline.assigned_to || 'Unassigned')}</strong></span
                  >
                </div>
                ${grant.pipeline.notes
                  ? `<p class="pipeline-notes">${esc(grant.pipeline.notes)}</p>`
                  : ''}${grant.pipeline.final_result
                  ? `<p class="pipeline-notes">Result: ${esc(grant.pipeline.final_result)}</p>`
                  : ''}
              </div>
              <details class="pipeline-edit-details">
                <summary>Edit tracking ${icon('chevron')}</summary>
                <div class="pipeline-inline-editor">${pipelineForm(grant, token)}</div>
              </details>
            </article>`,
        )
        .join('');
      return `<section id="status-${stage.toLowerCase()}" class="pipeline-stage"><div class="section-heading"><h2><span class="stage-dot stage-${stage.toLowerCase()}"></span>${stage} <span class="count-pill">${grants.length}</span></h2></div>${cards || '<p class="empty-stage">No opportunities in this stage yet.</p>'}</section>`;
    })
    .join('');
  return /* HTML */ ` <section class="page-heading">
      <div>
        <p class="eyebrow teal">FROM POSSIBILITY TO PROGRESS</p>
        <h1>Your funding pipeline.</h1>
        <p class="lede">
          Track the opportunities you're pursuing and the next steps that move them forward.
        </p>
      </div>
      <a class="button button-primary" href="/">${icon('search')} Discover grants</a>
    </section>
    <div class="pipeline-stats" aria-label="Opportunities by pipeline status">${counters}</div>
    <section class="panel">
      <form method="get">
        <div class="grid">
          ${select('pipeline_status', query.pipeline_status, ['', ...statuses])}
        </div>
        <div class="form-actions">
          <button class="button button-secondary">Filter pipeline</button
          ><a href="/pipeline">Clear filters</a>
        </div>
      </form>
    </section>
    <div class="pipeline-sections">${stages}</div>`;
}
