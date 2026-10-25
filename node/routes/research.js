import { dispositions } from '../service.js';
import { date } from '../validation.js';
import { now } from '../store.js';
import * as ui from '../views.js';

// Staff preferences remain separate from source facts and legal eligibility.
export function registerResearchRoutes(app, { store, send, redirect }) {
  app.get('/research', async (req, res) =>
    send(req, res, 'Team research', ui.research(await store.read(), req.session.csrf)),
  );
  app.post('/research/:id', async (req, res) => {
    if (!dispositions.includes(req.body.disposition))
      throw new Error('Invalid research disposition.');
    const review_on = req.body.review_on ? date.parse(req.body.review_on) : null;
    await store.update((s) => {
      const p = s.prospects.find((p) => p.id === req.params.id);
      if (!p) throw new Error('Research prospect not found.');
      Object.assign(p, {
        disposition: req.body.disposition,
        review_on,
        team_notes: String(req.body.team_notes || ''),
        updated_at: now(),
      });
    });
    redirect(res, '/research', 'Staff decision saved.');
  });
}
