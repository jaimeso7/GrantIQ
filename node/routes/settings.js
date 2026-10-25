import { profileSchema, lines, number, triBool, weights } from '../validation.js';
import { rescore } from '../service.js';
import * as ui from '../views.js';

// Parse browser strings into the profile contract, then rescore atomically.
export function registerSettingsRoutes(app, { store, send, redirect }) {
  app.get('/settings', async (req, res) =>
    send(
      req,
      res,
      'Organization profile',
      ui.settings((await store.read()).profile, req.session.csrf),
    ),
  );
  app.post('/settings', async (req, res) => {
    const b = req.body,
      p = { ...b };
    for (const k of [
      'service_locations',
      'populations_served',
      'programs',
      'funding_interests',
      'invited_by_funders',
      'existing_funder_relationships',
      'excluded_funders',
    ])
      p[k] = lines(b[k]);
    for (const k of [
      'minimum_desired_award',
      'maximum_desired_award',
      'annual_budget',
      'minimum_days_to_apply',
    ])
      p[k] = number(b[k]);
    for (const k of ['matching_funds_available', 'has_fiscal_sponsor']) p[k] = triBool(b[k]);
    p.readiness_thresholds = String(b.readiness_thresholds)
      .split(',')
      .map((x) => Number(x.trim()));
    p.profile_source_url = b.profile_source_url || null;
    p.weights = Object.fromEntries(Object.keys(weights).map((k) => [k, Number(b['weight_' + k])]));
    const profile = profileSchema.parse(p);
    await store.update(async (s) => {
      s.profile = profile;
      await rescore(s);
    });
    redirect(res, '/settings', 'Organization profile and assessments updated.');
  });
}
