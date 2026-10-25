import { createHash } from 'node:crypto';
import { equal } from '../security.js';
import * as ui from '../views.js';

// Sign-in throttling is persisted so restarting a hosted instance cannot reset it.
export function registerAuthRoutes(app, { store, config, sessions, send, redirect }) {
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
}
