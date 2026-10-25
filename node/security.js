import { createHmac, createHash, randomBytes, timingSafeEqual } from 'node:crypto';
import cookieParser from 'cookie-parser';
const digest = (v) => createHash('sha256').update(String(v)).digest();
export const equal = (a, b) => timingSafeEqual(digest(a), digest(b));
export function security(app, config) {
  const secret = config.secret || randomBytes(32).toString('hex');
  const sign = (v) => createHmac('sha256', secret).update(v).digest('base64url');
  const options = {
    httpOnly: true,
    sameSite: 'strict',
    secure: config.production,
    path: '/',
    maxAge: 8 * 3600000,
  };
  function issue(res, auth) {
    const session = { auth, csrf: randomBytes(24).toString('hex'), exp: Date.now() + 8 * 3600000 };
    const data = Buffer.from(JSON.stringify(session)).toString('base64url');
    res.cookie('grantiq_node', `${data}.${sign(data)}`, options);
    return session;
  }
  app.disable('x-powered-by');
  app.use(cookieParser());
  app.use((req, res, next) => {
    res.set({
      'X-Content-Type-Options': 'nosniff',
      'X-Frame-Options': 'DENY',
      'Referrer-Policy': 'same-origin',
      'Cache-Control': 'no-store',
      'Content-Security-Policy':
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
    });
    if (config.production) res.set('Strict-Transport-Security', 'max-age=31536000');
    if (!config.allowedHosts.includes(req.hostname.toLowerCase()))
      return res.status(400).send('Unexpected host.');
    if (
      !config.password &&
      !['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(req.socket.remoteAddress)
    )
      return res.status(403).send('Local-only instance.');
    let session = null;
    try {
      const [data, sig] = String(req.cookies.grantiq_node || '').split('.');
      if (data && sig && equal(sign(data), sig)) {
        const parsed = JSON.parse(Buffer.from(data, 'base64url'));
        if (parsed.exp > Date.now()) session = parsed;
      }
    } catch {}
    req.session = session || issue(res, false);
    res.locals.csrf = req.session.csrf;
    if (!['GET', 'HEAD', 'OPTIONS'].includes(req.method)) {
      if (!equal(req.body?._csrf || '', req.session.csrf))
        return res.status(403).send('Form expired or invalid. Reload and try again.');
      if (req.headers.origin) {
        try {
          if (new URL(req.headers.origin).host !== req.get('host'))
            return res.status(403).send('Cross-origin form refused.');
        } catch {
          return res.status(403).send('Invalid origin.');
        }
      }
    }
    const publicPath = [
      '/health',
      '/login',
      '/static/original.css',
      '/static/node.css',
      '/static/node.js',
    ].includes(req.path);
    if (config.password && !req.session.auth && !publicPath) {
      if (req.path.startsWith('/api/')) return res.status(401).json({ error: 'Sign in required.' });
      return res.redirect(303, '/login');
    }
    next();
  });
  return {
    login: (res) => issue(res, true),
    logout: (res) => res.clearCookie('grantiq_node', { ...options, maxAge: undefined }),
  };
}
