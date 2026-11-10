import { watch } from '../ui/watch.js';
import { httpUrl } from '../validation.js';
import { publicAddress } from '../network.js';
import { upsert } from '../service.js';
import { dispositions } from '../service.js';
import { date } from '../validation.js';
import { now } from '../store.js';
import * as ui from '../views.js';

// Staff preferences remain separate from source facts and legal eligibility.
export function registerResearchRoutes(app, { store, send, redirect, fresh }) {
  app.get('/watch', async (req, res) =>
    send(req, res, 'Grant watch', watch(await fresh(), req.session.csrf)),
  );
  app.post('/research/leads/:id/opportunity', async (req, res) => {
    const url = httpUrl.parse(req.body.official_url);
    await publicAddress(url);
    if (!req.body.funder_name?.trim() || !req.body.grant_title?.trim())
      throw new Error('Funder and program names are required.');
    let grantId;
    await store.update(async (s) => {
      const lead = (s.discoveryLeads || []).find((l) => l.id === req.params.id);
      if (!lead) throw new Error('Lead not found.');
      const existing = s.grants.find(
        (g) => g.record.source === 'Staff research' && g.record.source_id === lead.id,
      );
      if (existing) {
        grantId = existing.id;
        return;
      }
      await upsert(s, {
        source: 'Staff research',
        source_id: lead.id,
        source_url: url,
        funder_name: req.body.funder_name.trim().slice(0, 200),
        grant_title: req.body.grant_title.trim().slice(0, 500),
        warnings: [
          'Research lead: verify official eligibility, current cycle and application route.',
        ],
      });
      grantId = s.grants.find(
        (g) => g.record.source === 'Staff research' && g.record.source_id === lead.id,
      ).id;
      lead.disposition = 'Converted';
    });
    redirect(res, '/grants/' + grantId + '/verify', 'Opportunity created with unverified facts.');
  });
  app.post('/research/leads/:id', async (req, res) => {
    if (
      !['Verify', 'Cultivate', 'Monitor', 'Dismissed', 'Converted'].includes(req.body.disposition)
    )
      throw new Error('Invalid lead disposition.');
    await store.update((s) => {
      const lead = (s.discoveryLeads || []).find((l) => l.id === req.params.id);
      if (!lead) throw new Error('Lead not found.');
      lead.disposition = req.body.disposition;
      lead.notes = String(req.body.notes || '').slice(0, 10000);
    });
    redirect(res, '/watch', 'Research lead updated.');
  });
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
