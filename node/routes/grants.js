import { pipelineSchema, number } from '../validation.js';
import { views, filterGrants } from '../service.js';
import { now } from '../store.js';
import * as ui from '../views.js';

// Read discovery views; only validated tracking fields may update the staff pipeline.
export function registerGrantsRoutes(app, { store, send, redirect, grant, fresh }) {
  app.get('/', async (req, res) => {
    const s = await fresh();
    send(
      req,
      res,
      'Discover opportunities',
      ui.dashboard(s, filterGrants(views(s), req.query), req.query, req.session.csrf),
    );
  });
  app.get('/pipeline', async (req, res) => {
    const s = await fresh();
    send(
      req,
      res,
      'My pipeline',
      ui.pipeline(
        s,
        filterGrants(
          views(s).filter((g) => g.pipeline),
          { ...req.query, include_closed: '1', include_staff_hidden: '1' },
        ),
        req.query,
        req.session.csrf,
      ),
    );
  });
  app.get('/grants/:id', async (req, res) => {
    const s = await fresh(),
      g = grant(s, req.params.id);
    send(
      req,
      res,
      g.record.grant_title,
      ui.detail(
        views(s).find((x) => x.id === g.id),
        req.session.csrf,
      ),
    );
  });
  app.post('/grants/:id/pipeline', async (req, res) => {
    const p = pipelineSchema.parse({
      ...req.body,
      requested_amount: number(req.body.requested_amount),
      application_deadline: req.body.application_deadline || null,
      submission_date: req.body.submission_date || null,
    });
    await store.update((s) => {
      grant(s, req.params.id).pipeline = { ...p, updated_at: now() };
    });
    redirect(res, `/grants/${Number(req.params.id)}`, 'Pipeline saved.');
  });
}
