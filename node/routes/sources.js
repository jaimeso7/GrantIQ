import { randomUUID } from 'node:crypto';
import { httpUrl } from '../validation.js';
import { status } from '../service.js';
import { publicAddress } from '../network.js';
import { now, hoursAfter } from '../store.js';
import * as ui from '../views.js';

// Approve public source URLs before fetching them; scheduling persists across redeploys.
export function registerSourcesRoutes(app, { store, discovery, send, redirect }) {
  app.get('/api/search-status', async (_req, res) => res.json(status(await store.read())));
  app.post('/refresh', async (_req, res) => {
    discovery.run().catch((e) => console.error('Refresh failed:', e.message));
    redirect(res, '/sources', 'Search requested. Check the live status and results below.');
  });
  app.get('/sources', async (req, res) =>
    send(req, res, 'Data sources', ui.sources(await store.read(), req.session.csrf)),
  );
  app.post('/sources/schedule', async (req, res) => {
    const interval = Number(req.body.interval_hours);
    if (![3, 6, 12, 24].includes(interval) || !['yes', 'no'].includes(req.body.enabled))
      throw new Error('Choose a valid schedule.');
    await store.update((s) => {
      s.schedule.interval_hours = interval;
      s.schedule.enabled = req.body.enabled === 'yes';
      s.schedule.next_run_at = hoursAfter(interval);
    });
    redirect(res, '/sources', 'Schedule saved. An in-progress search will finish normally.');
  });
  app.get('/sources/new', (req, res) =>
    send(req, res, 'Add funding page', ui.sourceForm({}, req.session.csrf)),
  );
  app.get('/sources/:id/edit', async (req, res) => {
    const source = (await store.read()).sources.find((x) => String(x.id) === req.params.id);
    if (!source) return res.status(404).send('Source not found.');
    send(req, res, 'Edit funding page', ui.sourceForm(source, req.session.csrf));
  });
  const saveSource = async (req, res) => {
    const b = req.body,
      url = httpUrl.parse(b.url);
    await publicAddress(url);
    const enabled = b.enabled === 'yes',
      terms_reviewed = b.terms_reviewed === 'yes';
    if (enabled && (!terms_reviewed || !String(b.reviewed_by || '').trim()))
      throw new Error('Enabled sources need terms review and a reviewer name.');
    if (!b.name?.trim() || b.name.length > 200)
      throw new Error('Source name is required (up to 200 characters).');
    const selectors = JSON.parse(b.selectors || '{}');
    const allowed = [
      'title',
      'description',
      'eligibility',
      'deadline',
      'award_min',
      'award_max',
      'application_url',
      'applicant_types',
      'geographic_restrictions',
      'geography_scope',
      'populations_served',
      'categories',
      'program_areas',
      'status',
    ];
    if (
      !selectors ||
      Array.isArray(selectors) ||
      typeof selectors !== 'object' ||
      Object.entries(selectors).some(
        ([k, v]) => !allowed.includes(k) || typeof v !== 'string' || v.length > 500,
      )
    )
      throw new Error('Use supported selector keys and CSS selector strings.');
    await store.update((s) => {
      let source = req.params.id ? s.sources.find((x) => String(x.id) === req.params.id) : null;
      if (req.params.id && !source) throw new Error('Source not found.');
      if (s.sources.some((x) => x.url === url && x !== source))
        throw new Error('This source URL is already registered.');
      if (!source) {
        source = { id: randomUUID() };
        s.sources.push(source);
      }
      Object.assign(source, {
        name: b.name.trim(),
        url,
        enabled,
        terms_reviewed,
        reviewed_by: String(b.reviewed_by || ''),
        terms_reference: String(b.terms_reference || ''),
        selectors,
        updated_at: now(),
      });
    });
    redirect(res, '/sources', 'Funding page saved.');
  };
  app.post('/sources', saveSource);
  app.post('/sources/:id', saveSource);
}
