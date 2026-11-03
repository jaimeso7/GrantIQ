import { test } from 'node:test';
import assert from 'node:assert/strict';
import { configuration } from '../config.js';
import { createStore } from '../store.js';
import { seed } from './helpers.js';
test('production fails closed without database, password, secret and host', () => {
  assert.throws(() => configuration({ NODE_ENV: 'production' }), /Production requires/);
  const c = configuration({
    NODE_ENV: 'production',
    GRANTIQ_ADMIN_PASSWORD: 'test',
    GRANTIQ_SECRET_KEY: 'a'.repeat(32),
    GRANTIQ_ALLOWED_HOSTS: 'demo.example.org',
    GRANTIQ_DATABASE_URL: 'postgresql://user:password@example.org/db',
  });
  assert.equal(c.host, '0.0.0.0');
  assert.equal(c.production, true);
  assert.throws(() => configuration({ HOST: '0.0.0.0' }), /loopback/);
});

test('Railway infers production, public domain and standard database reference', () => {
  const c = configuration({
    RAILWAY_PROJECT_ID: 'test-project',
    RAILWAY_PUBLIC_DOMAIN: 'grantiq.up.railway.app',
    NODE_ENV: 'development',
    DATABASE_URL: 'postgresql://user:password@postgres.railway.internal:5432/railway',
    GRANTIQ_ADMIN_PASSWORD: 'test-only',
    GRANTIQ_SECRET_KEY: 'x'.repeat(32),
    PORT: '8080',
  });
  assert.equal(c.production, true);
  assert.equal(c.host, '0.0.0.0');
  assert.equal(c.port, 8080);
  assert.deepEqual(c.allowedHosts, ['grantiq.up.railway.app', 'healthcheck.railway.app']);
  assert.match(c.databaseUrl, /postgres.railway.internal/);
});

test('Railway setup fails closed and errors never disclose credentials', () => {
  assert.throws(() => configuration({ RAILWAY_PROJECT_ID: 'test' }), /GRANTIQ_ADMIN_PASSWORD/);
  assert.throws(
    () => configuration({ GRANTIQ_ALLOWED_HOSTS: 'https://example.org/path' }),
    /exact hostnames/,
  );
  assert.throws(() => configuration({ GRANTIQ_ALLOWED_HOSTS: '*.example.org' }), /exact hostnames/);
  try {
    configuration({ NODE_ENV: 'production', DATABASE_URL: 'https://user:private-secret@host/db' });
    assert.fail('Invalid production settings accepted');
  } catch (error) {
    assert.ok(!error.message.includes('private-secret'));
    assert.match(error.message, /PostgreSQL reference/);
  }
});

test('explicit GrantIQ database and custom hosts coexist with Railway defaults', () => {
  const c = configuration({
    RAILWAY_PROJECT_ID: 'test',
    RAILWAY_PUBLIC_DOMAIN: 'demo.up.railway.app',
    GRANTIQ_ALLOWED_HOSTS: 'grants.example.org, grants.example.org',
    GRANTIQ_DATABASE_URL: 'postgres://custom.example.org/db',
    DATABASE_URL: 'postgres://unused.example.org/db',
    GRANTIQ_ADMIN_PASSWORD: 'test',
    GRANTIQ_SECRET_KEY: 'x'.repeat(32),
  });
  assert.equal(c.databaseUrl, 'postgres://custom.example.org/db');
  assert.deepEqual(c.allowedHosts, [
    'grants.example.org',
    'demo.up.railway.app',
    'healthcheck.railway.app',
  ]);
});
test(
  'PostgreSQL persistence and locks across independent connections',
  { skip: !process.env.GRANTIQ_TEST_POSTGRES_URL },
  async () => {
    const c = { ...configuration({}), databaseUrl: process.env.GRANTIQ_TEST_POSTGRES_URL };
    const a = await createStore(c, seed),
      b = await createStore(c, seed);
    try {
      await a.update((s) => {
        Object.assign(s, seed());
        s.cursor = 0;
      });
      await Promise.all(
        Array.from({ length: 20 }, (_, i) =>
          (i % 2 ? a : b).update((s) => {
            s.cursor++;
          }),
        ),
      );
      assert.equal((await a.read()).cursor, 20);
      const leases = await Promise.all([a.acquireLease(), b.acquireLease()]);
      assert.equal(leases.filter(Boolean).length, 1);
      await assert.rejects(
        a.update((s) => {
          s.cursor = 99;
          throw new Error('abort');
        }),
      );
      assert.equal((await b.read()).cursor, 20);
    } finally {
      await a.close();
      await b.close();
    }
  },
);
