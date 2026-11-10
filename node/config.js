import path from 'node:path';
import { fileURLToPath } from 'node:url';
export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

// Hostnames are configuration, never inferred from an incoming request. Reject
// URLs/wildcards so a setup typo cannot silently weaken the Host-header check.
function hostnames(value) {
  return value
    .split(',')
    .map((host) => host.trim().toLowerCase())
    .filter(Boolean);
}

export function configuration(env = process.env) {
  const railway = !!env.RAILWAY_PROJECT_ID;
  // Railway must never accidentally start the unauthenticated local-development mode.
  const production = railway || env.NODE_ENV === 'production';
  const password = env.GRANTIQ_ADMIN_PASSWORD || '';
  const secret = env.GRANTIQ_SECRET_KEY || '';
  const configuredHosts = hostnames(env.GRANTIQ_ALLOWED_HOSTS || '');
  if (railway && env.RAILWAY_PUBLIC_DOMAIN)
    configuredHosts.push(...hostnames(env.RAILWAY_PUBLIC_DOMAIN));
  if (configuredHosts.some((host) => !/^(?:[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?|::1)$/.test(host)))
    throw new Error(
      'Allowed hosts must be exact hostnames without https://, ports, paths or wildcards.',
    );
  // Railway's readiness request uses a special Host. It grants no access to private pages.
  const allowedHosts = [
    ...new Set([
      ...configuredHosts,
      ...(railway ? ['healthcheck.railway.app'] : []),
      ...(!production && !configuredHosts.length ? ['localhost', '127.0.0.1'] : []),
    ]),
  ];
  const databaseUrl = env.GRANTIQ_DATABASE_URL || env.DATABASE_URL || '';
  const missing = [];
  if (!password.trim()) missing.push('GRANTIQ_ADMIN_PASSWORD');
  if (secret.length < 32) missing.push('GRANTIQ_SECRET_KEY (32+ characters)');
  if (!configuredHosts.length)
    missing.push('GRANTIQ_ALLOWED_HOSTS (or generate a Railway public domain)');
  let databaseValid = false;
  try {
    const parsed = new URL(databaseUrl);
    databaseValid = ['postgres:', 'postgresql:'].includes(parsed.protocol) && !!parsed.hostname;
  } catch {
    /* Report the setting name below, never a URL containing a password. */
  }
  if (!databaseValid) missing.push('GRANTIQ_DATABASE_URL or DATABASE_URL (PostgreSQL reference)');
  if (production && missing.length) {
    throw new Error(`Production requires: ${missing.join('; ')}. See RAILWAY.md for setup.`);
  }
  const port = Number(env.PORT || 3000);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('PORT must be 1–65535.');
  const host = env.HOST || (production ? '0.0.0.0' : '127.0.0.1');
  if (!production && !password && !['127.0.0.1', '::1', 'localhost'].includes(host))
    throw new Error('Unauthenticated mode must bind to loopback.');
  return {
    foundationDiscovery: env.GRANTIQ_FOUNDATION_DISCOVERY !== 'false',
    webSearchKey: env.GRANTIQ_BRAVE_API_KEY || '',
    production,
    password,
    secret,
    allowedHosts,
    databaseUrl,
    port,
    host,
    dataDir: path.resolve(env.GRANTIQ_NODE_DATA_DIR || path.join(root, 'data/node')),
    databaseSsl: env.GRANTIQ_DATABASE_SSL === 'require',
    scheduler: env.GRANTIQ_SCHEDULER !== 'false',
    maxRecords: Math.max(1, Math.min(10000, Number(env.GRANTIQ_MAX_RECORDS) || 100)),
  };
}
