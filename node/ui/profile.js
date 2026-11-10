import { input, textarea, select, form } from './html.js';

export function settings(p, token) {
  return /* HTML */ `<p class="lead">
      These settings drive eligibility, scoring, and discovery. List one item per line.
    </p>
    ${form(
      '/settings',
      token,
      /* HTML */ `<section class="panel">
          <h2>Organization</h2>
          <div class="grid">
            ${['name', 'organization_type', 'ein', 'profile_source_url']
              .map((k) => input(k, p[k], k === 'profile_source_url' ? 'url' : 'text'))
              .join('')}${input('annual_budget', p.annual_budget, 'number', 'min="0" step="0.01"')}
          </div>
          ${textarea('mission', p.mission)}${textarea('description', p.description)}
        </section>
        <section class="panel">
          <h2>Communities and programs</h2>
          <div class="grid">
            ${['service_locations', 'populations_served', 'programs', 'funding_interests']
              .map((k) => textarea(k, p[k]))
              .join('')}
          </div>
        </section>
        <section class="panel">
          <h2>Funding and readiness</h2>
          <div class="grid">
            ${['minimum_desired_award', 'maximum_desired_award', 'minimum_days_to_apply']
              .map((k) => input(k, p[k], 'number', 'min="0" step="0.01"'))
              .join('')}${input('readiness_thresholds', p.readiness_thresholds.join(', '))}${[
              'matching_funds_available',
              'has_fiscal_sponsor',
            ]
              .map((k) =>
                select(k, p[k] === null ? 'unknown' : p[k] ? 'yes' : 'no', [
                  'unknown',
                  'yes',
                  'no',
                ]),
              )
              .join('')}
          </div>
          <div class="grid">
            ${['invited_by_funders', 'existing_funder_relationships', 'excluded_funders']
              .map((k) => textarea(k, p[k]))
              .join('')}
          </div>
        </section>
        <section class="panel">
          <h2>Grant-watch scoring policy</h2>
          <p>
            Mission/programs 25 Â· Geography 20 Â· Populations 15 Â· Eligible expenses 15 Â·
            Application accessibility 10 Â· Funding value 10 Â· Timing 5.
          </p>
          <p>
            90+ Exceptional Fit Â· 75â€“89 Strong Fit Â· 60â€“74 Moderate Fit Â· below 60 Lower
            Priority. Unverified eligibility makes the score provisional. Explicit exclusion
            disqualifies an opportunity.
          </p>
        </section>`,
      'Save profile and rescore',
    )}`;
}
