import * as ui from '../views.js';
import { rescore } from '../service.js';
import { today } from '../store.js';

// Keep redirects, date-sensitive scoring and missing-grant errors consistent.
export function createRouteContext(store, config, discovery, sessions) {
  const send = (req, res, title, body) =>
    res.send(
      ui.layout(title, body, {
        token: req.session.csrf,
        notice: typeof req.query.notice === 'string' ? req.query.notice : '',
        auth: !!config.password && req.session.auth,
        pathname: req.path,
        organization: res.locals.organization,
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
    // Deadlines and verification expiry can change eligibility without new source data.
    // Refresh stale assessments on the next page read, using the same scoring path.
    const s = await store.read();
    if (s.grants.some((g) => !g.assessment || g.assessment.scored_at.slice(0, 10) < today())) {
      await store.update(rescore);
      return store.read();
    }
    return s;
  };

  return { store, config, discovery, sessions, send, redirect, grant, fresh };
}
