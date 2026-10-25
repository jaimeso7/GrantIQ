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
