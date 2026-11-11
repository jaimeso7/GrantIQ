import { randomUUID } from 'node:crypto';
import { grantSchema, httpUrl, date, lines, number, triBool } from '../validation.js';
import { reviewFields, revision, effective } from '../matching.js';
import { assess } from '../service.js';
import { now, today } from '../store.js';
import * as ui from '../views.js';

// Reviews retain evidence and source revisions; withdrawal appends history.
export function registerVerificationRoutes(app, { store, send, redirect, grant, fresh }) {
  app.get('/grants/:id/verify', async (req, res) => {
    const s = await fresh();
    const g = grant(s, req.params.id);
    send(
      req,
      res,
      'Verify source facts',
      ui.verification({ ...g, ...effective(g) }, req.session.csrf),
    );
  });
  app.post('/grants/:id/verify', async (req, res) => {
    const b = req.body,
      fields = [b.fields || []].flat();
    if (!fields.length || fields.some((k) => !reviewFields.some((f) => f[0] === k)))
      throw new Error('Select at least one supported fact.');
    const evidence_url = httpUrl.parse(b.evidence_url),
      valid_until = date.parse(b.valid_until);
    if (valid_until < today() || Date.parse(valid_until) - Date.parse(today()) > 180 * 86400000)
      throw new Error('Review expiry must be today through 180 days from today.');
    if (!b.reviewed_by?.trim() || !b.evidence_note?.trim())
      throw new Error('Reviewer and supporting evidence notes are required.');
    const facts = {};
    for (const key of fields) {
      const type = reviewFields.find((f) => f[0] === key)[2];
      facts[key] =
        type === 'list'
          ? lines(b[key])
          : type === 'bool'
            ? triBool(b[key])
            : type === 'number'
              ? number(b[key])
              : ['date', 'url'].includes(type)
                ? b[key] || null
                : String(b[key] || '');
    }
    await store.update(async (s) => {
      const g = grant(s, req.params.id),
        validated = grantSchema.parse({ ...g.record, ...facts });
      g.reviews.push({
        id: randomUUID(),
        facts: Object.fromEntries(fields.map((k) => [k, validated[k]])),
        source_revision: revision(g.record),
        evidence_url,
        evidence_note: b.evidence_note,
        reviewed_by: b.reviewed_by,
        reviewed_at: now(),
        valid_until,
        action: 'verified',
      });
      g.assessment = await assess(g, s.profile);
    });
    redirect(
      res,
      `/grants/${Number(req.params.id)}`,
      'Verified facts saved; assessment recalculated.',
    );
  });
  app.post('/grants/:id/verify/withdraw', async (req, res) => {
    if (!req.body.reviewed_by?.trim()) throw new Error('Reviewer is required.');
    await store.update(async (s) => {
      const g = grant(s, req.params.id),
        latest = g.reviews.at(-1);
      if (!latest) throw new Error('No verification to withdraw.');
      g.reviews.push({
        ...latest,
        id: randomUUID(),
        action: 'withdrawn',
        reviewed_at: now(),
        reviewed_by: req.body.reviewed_by,
      });
      g.assessment = await assess(g, s.profile);
    });
    redirect(res, `/grants/${Number(req.params.id)}`, 'Verification withdrawn; history retained.');
  });
}
