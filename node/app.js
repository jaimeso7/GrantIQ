import express from 'express';
import path from 'node:path';
import fs from 'node:fs';
import { randomUUID, createHash } from 'node:crypto';
import { security, equal } from './security.js';
import { root } from './config.js';
import {
  profileSchema,
  pipelineSchema,
  grantSchema,
  httpUrl,
  date,
  lines,
  number,
  triBool,
  weights,
} from './validation.js';
import { views, filterGrants, rescore, assess, status, dispositions } from './service.js';
import { reviewFields, revision, effective } from './matching.js';
import { publicAddress } from './network.js';
import { now, today, hoursAfter } from './store.js';
import * as ui from './views.js';

export function createApp(store, config, discovery) {
  const app = express();
  app.set('query parser', 'simple');
  app.use(express.urlencoded({ extended: false, limit: '256kb', parameterLimit: 500 }));
  const sessions = security(app, config);
  app.use(
    '/static',
    express.static(path.join(root, 'node/public'), { dotfiles: 'deny', index: false }),
  );
  const send = (req, res, title, body) =>
    res.send(
      ui.layout(title, body, {
        token: req.session.csrf,
        notice: typeof req.query.notice === 'string' ? req.query.notice : '',
        auth: !!config.password && req.session.auth,
      }),
    );
  const redirect = (res, url, notice) =>
    res.redirect(303, url + (url.includes('?') ? '&' : '?') + new URLSearchParams({ notice }));
  const grant = (s, id) => {
    const g = s.grants.find((g) => g.id === Number(id));
    if (!g) {
      const e = new Error('Opportunity not found.');
      e.status = 404;
      throw e;
    }
    return g;
  };
  const fresh = async () => {
    const s = await store.read();
    if (s.grants.some((g) => !g.assessment || g.assessment.scored_at.slice(0, 10) < today())) {
      await store.update(rescore);
      return store.read();
    }
    return s;
  };
  app.get('/health', async (_req, res) => {
    await store.read();
    res.json({ status: 'ok', application: 'GrantIQ', runtime: 'node' });
  });
  app.get('/login', (req, res) =>
    send(
      req,
      res,
      'Sign in',
      `<section class="panel">${ui.form('/login', req.session.csrf, ui.input('password', '', 'password', 'required autocomplete="current-password"'), 'Sign in')}</section>`,
    ),
  );
  app.post('/login', async (req, res) => {
    const key = createHash('sha256')
      .update(req.socket.remoteAddress || 'unknown')
      .digest('hex');
    const allowed = await store.update((s) => {
      const cutoff = Date.now() - 15 * 60000;
      for (const [k, v] of Object.entries(s.loginAttempts))
        if (v.last < cutoff) delete s.loginAttempts[k];
      const entry = s.loginAttempts[key] || { count: 0, last: Date.now() };
      if (entry.count >= 10) return false;
      entry.count++;
      entry.last = Date.now();
      s.loginAttempts[key] = entry;
      return true;
    });
    if (!allowed)
      return res.status(429).send('Too many sign-in attempts. Try again after 15 minutes.');
    if (!config.password || !equal(req.body.password, config.password))
      return res
        .status(401)
        .send(
          ui.layout('Sign-in failed', '<p>Incorrect password. <a href="/login">Try again</a>.</p>'),
        );
    await store.update((s) => {
      delete s.loginAttempts[key];
    });
    sessions.login(res);
    res.redirect(303, '/');
  });
  app.post('/logout', (_req, res) => {
    sessions.logout(res);
    res.redirect(303, '/login');
  });
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
  app.get('/export.csv', async (req, res) => {
    const s = await fresh(),
      items = filterGrants(views(s), req.query);
    const cell = (v) =>
      '"' +
      String(v ?? '')
        .replace(/^[\s]*[=+@\-\t\r]/, (m) => "'" + m)
        .replaceAll('"', '""') +
      '"';
    const rows = [
      [
        'Title',
        'Funder',
        'Fit score',
        'Eligibility',
        'Confidence',
        'Deadline',
        'Source URL',
        'Stage',
        'Assignee',
        'Requested amount',
        'Staff deadline',
        'Submission date',
        'Notes',
        'Final result',
      ],
      ...items.map((g) => [
        g.record.grant_title,
        g.record.funder_name,
        g.assessment.fit_score,
        g.assessment.eligibility_status,
        g.assessment.confidence_score,
        g.record.deadline,
        g.record.source_url,
        g.pipeline?.status || 'Discovered',
        g.pipeline?.assigned_to,
        g.pipeline?.requested_amount,
        g.pipeline?.application_deadline,
        g.pipeline?.submission_date,
        g.pipeline?.notes,
        g.pipeline?.final_result,
      ]),
    ];
    res
      .attachment('grantiq.csv')
      .type('text/csv')
      .send('\uFEFF' + rows.map((r) => r.map(cell).join(',')).join('\r\n'));
  });
  app.get('/sprint-review', (req, res) =>
    send(
      req,
      res,
      'GrantIQ on Node.js',
      `<section class="panel"><h2>How the application works</h2><p>Organization profile + research keywords → recurring source discovery → eligibility checks → explainable matching → persistent database → staff pipeline.</p><p>The Node.js runtime uses Express, PostgreSQL for hosting, and optional local MiniLM through Transformers.js. No Python process is required.</p><p>Hosted setup uses shared staff sign-in. Individual accounts and roles are future work. Follow SITEGROUND.md in the repository for deployment and validation.</p><p><a href="/sources">Show actual search status</a> · <a href="/pipeline">Show the team pipeline</a></p></section>`,
    ),
  );
  app.use((_req, res) =>
    res.status(404).send(ui.layout('Not found', '<p><a href="/">Return to GrantIQ</a></p>')),
  );
  app.use((error, req, res, _next) => {
    const message = error.issues
      ? error.issues.map((x) => `${x.path.join('.')}: ${x.message}`).join('; ')
      : error.message;
    const expected =
      error.name === 'ZodError' ||
      error.status ||
      !/(SQL|database|password authentication|connect ECONN)/i.test(message);
    console.error('Request failed:', error.name);
    res
      .status(error.status || 422)
      .send(
        ui.layout(
          'Unable to complete this action',
          `<section class="panel error"><p>${ui.esc(expected ? message : 'Storage unavailable. Contact the administrator.')}</p><p>Your previous saved data is retained. <a href="${ui.esc(req.path)}">Return to page</a></p></section>`,
          { token: req.session?.csrf },
        ),
      );
  });
  return app;
}
