import { esc, input, textarea, select, form } from './html.js';
import { searchPanel } from './discovery.js';

export function sources(s, token) {
  return /* HTML */ `${searchPanel(s, token)}
    <section class="panel" id="search-schedule">
      <h2>Search schedule</h2>
      ${form(
        '/sources/schedule',
        token,
        /* HTML */ `<div class="grid">
          ${select('interval_hours', s.schedule.interval_hours, [3, 6, 12, 24])}${select(
            'enabled',
            s.schedule.enabled ? 'yes' : 'no',
            ['yes', 'no'],
          )}
        </div>`,
        'Save search schedule',
      )}
    </section>
    <section class="panel">
      <h2>Approved funding pages</h2>
      <p>
        One public opportunity per page. Terms must be reviewed before enabling. Login controls and
        robots restrictions are respected.
      </p>
      <a class="button" href="/sources/new">Add funding page</a>${s.sources
        .map(
          (x) =>
            /* HTML */ `<p>
              <a href="/sources/${x.id}/edit">${esc(x.name)}</a> ·
              ${x.enabled ? 'Enabled' : 'Disabled'} · ${esc(x.url)}
            </p>`,
        )
        .join('')}
    </section>
    <section class="panel">
      <h2>Refresh activity</h2>
      ${[...s.runs]
        .reverse()
        .map(
          (r) =>
            /* HTML */ `<details>
              <summary>
                ${esc(r.status)} · ${esc(r.started_at)} · ${r.added || 0} added / ${r.updated || 0}
                updated
              </summary>
              <p>
                Found ${r.found || 0}; rejected ${r.rejected || 0}. Finished
                ${esc(r.finished_at || 'Still running')}.
              </p>
              <ul>
                ${(r.errors || []).map((e) => /* HTML */ `<li>${esc(e)}</li>`).join('')}
              </ul>
            </details>`,
        )
        .join('') || '<p>No searches yet.</p>'}
    </section>`;
}

export function sourceForm(s, token) {
  return /* HTML */ `<p>Saving checks the public address; collection occurs during a search.</p>
    ${form(
      s.id ? `/sources/${s.id}` : '/sources',
      token,
      /* HTML */ `<section class="panel">
        ${input('name', s.name, 'text', 'required maxlength="200"')}${input(
          'url',
          s.url,
          'url',
          'required',
        )}${input('reviewed_by', s.reviewed_by)}${input('terms_reference', s.terms_reference)}
        <div class="grid">
          ${select('enabled', s.enabled ? 'yes' : 'no', ['no', 'yes'])}${select(
            'terms_reviewed',
            s.terms_reviewed ? 'yes' : 'no',
            ['no', 'yes'],
          )}
        </div>
        ${textarea('selectors', JSON.stringify(s.selectors || {}, null, 2), 8)}
        <p>
          Optional JSON mapping: title, description, eligibility, deadline, award_min, award_max,
          application_url, applicant_types, geographic_restrictions, geography_scope,
          populations_served, categories, program_areas, status. Values are CSS selectors.
        </p>
      </section>`,
      'Save source',
    )}`;
}
