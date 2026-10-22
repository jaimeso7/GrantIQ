import path from 'node:path';
import { fileURLToPath } from 'node:url';
export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export function configuration(env = process.env) {
  const production = env.NODE_ENV === 'production';
  const password = env.GRANTIQ_ADMIN_PASSWORD || '';
  const secret = env.GRANTIQ_SECRET_KEY || '';
  const allowedHosts = (env.GRANTIQ_ALLOWED_HOSTS || 'localhost,127.0.0.1')
    .split(',')
    .map((x) => x.trim().toLowerCase());
  const databaseUrl = env.GRANTIQ_DATABASE_URL || '';
  if (
    production &&
    (!password ||
      secret.length < 32 ||
      !env.GRANTIQ_ALLOWED_HOSTS ||
      !/^postgres(?:ql)?:\/\//.test(databaseUrl))
  ) {
    throw new Error(
      'Production requires password, a 32+ character secret, allowed hosts, and GRANTIQ_DATABASE_URL (PostgreSQL).',
    );
  }
  const port = Number(env.PORT || 3000);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('PORT must be 1–65535.');
  const host = env.HOST || (production ? '0.0.0.0' : '127.0.0.1');
  if (!production && !password && !['127.0.0.1', '::1', 'localhost'].includes(host))
    throw new Error('Unauthenticated mode must bind to loopback.');
  return {
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
