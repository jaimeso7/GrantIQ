import { test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { tempStore, record } from './helpers.js';
import { createApp } from '../app.js';
import { upsert } from '../service.js';
async function fixture(t, password = '') {
  const { store, config } = await tempStore(t, {
    password,
    secret: 'test-secret-that-is-long-enough-for-sessions',
  });
  const app = createApp(store, config, { run: async () => {} });
  const server = await new Promise((resolve) => {
    const s = app.listen(0, '127.0.0.1', () => resolve(s));
  });
  t.after(
    () =>
      new Promise((resolve) => {
        server.close(resolve);
        server.closeAllConnections();
      }),
  );
  const url = `http://127.0.0.1:${server.address().port}`;
  let cookie = '',
    token = '';
  return {
    store,
    url,
    async get(route) {
      const r = await fetch(url + route, { redirect: 'manual', headers: { cookie } });
      const c = r.headers.get('set-cookie');
      if (c) cookie = c.split(';')[0];
      const text = await r.text();
      const match = /name="_csrf" value="([^"]+)"/.exec(text);
      if (match) token = match[1];
      return { r, text };
    },
    async post(route, body = {}, csrf = true) {
      const r = await fetch(url + route, {
        method: 'POST',
        redirect: 'manual',
        headers: { cookie, 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ ...body, ...(csrf ? { _csrf: token } : {}) }),
      });
      const c = r.headers.get('set-cookie');
      if (c) cookie = c.split(';')[0];
      return r;
    },
  };
}
test('all public workflow pages render with escaping', async (t) => {
  const f = await fixture(t);
  await f.store.update((s) => upsert(s, record({ grant_title: '<script>alert(1)</script>' })));
  for (const path of [
    '/',
    '/settings',
    '/pipeline',
    '/sources',
    '/sources/new',
    '/research',
    '/grants/1',
    '/grants/1/verify',
    '/sprint-review',
  ]) {
    const { r, text } = await f.get(path);
    assert.equal(r.status, 200, path);
    assert.ok(!text.includes('<script>alert(1)</script>'));
  }
  assert.match((await f.get('/')).text, /&lt;script&gt;/);
});
test('CSRF blocks mutations; pipeline survives valid form submit', async (t) => {
  const f = await fixture(t);
  await f.store.update((s) => upsert(s, record()));
  await f.get('/grants/1');
  assert.equal(
    (await f.post('/grants/1/pipeline', { status: 'Applying', notes: 'test' }, false)).status,
    403,
  );
  assert.equal(
    (await f.post('/grants/1/pipeline', { status: 'Applying', notes: 'test' })).status,
    303,
  );
  assert.equal((await f.store.read()).grants[0].pipeline.notes, 'test');
});
test('private pages require sign-in and session rotates after login', async (t) => {
  const f = await fixture(t, 'correct-password');
  assert.equal((await f.get('/')).r.status, 303);
  await f.get('/login');
  assert.equal((await f.post('/login', { password: 'wrong' })).status, 401);
  assert.equal((await f.post('/login', { password: 'correct-password' })).status, 303);
  assert.equal((await f.get('/settings')).r.status, 200);
  await f.post('/logout');
  assert.equal((await f.get('/api/search-status')).r.status, 401);
});
test('CSV neutralizes spreadsheet formulas in staff notes', async (t) => {
  const f = await fixture(t);
  await f.store.update(async (s) => {
    await upsert(s, record());
    s.grants[0].pipeline = { status: 'Applying', notes: '=HYPERLINK("evil")' };
  });
  assert.match((await f.get('/export.csv')).text, /'=HYPERLINK/);
});
test('invalid pipeline mutation does not alter stored record', async (t) => {
  const f = await fixture(t);
  await f.store.update((s) => upsert(s, record()));
  await f.get('/grants/1');
  assert.equal((await f.post('/grants/1/pipeline', { status: 'made up' })).status, 422);
  assert.equal((await f.store.read()).grants[0].pipeline, null);
});
test('host header validation rejects untrusted hosts', async (t) => {
  const f = await fixture(t);
  const code = await new Promise((resolve, reject) => {
    const r = http.get(f.url + '/health', { headers: { Host: 'attacker.example' } }, (res) => {
      res.resume();
      resolve(res.statusCode);
    });
    r.on('error', reject);
  });
  assert.equal(code, 400);
});
