import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { tempStore, profile, record } from './helpers.js';
import { importPython } from '../scripts/import-python.js';
test('read-only SQLite import preserves staff work and refuses an occupied destination', async (t) => {
  const { store, dataDir } = await tempStore(t),
    file = path.join(dataDir, 'python.db');
  const db = new DatabaseSync(file);
  db.exec(
    'CREATE TABLE organizations(id INTEGER,profile TEXT);CREATE TABLE grants(id INTEGER,fingerprint TEXT,details TEXT,date_discovered TEXT);CREATE TABLE pipeline_entries(grant_id INTEGER,status TEXT,notes TEXT);CREATE TABLE source_records(grant_id INTEGER,source TEXT,source_id TEXT,source_url TEXT);',
  );
  db.prepare('INSERT INTO organizations VALUES(1,?)').run(JSON.stringify(profile()));
  db.prepare('INSERT INTO grants VALUES(42,?,?,?)').run(
    'fingerprint',
    JSON.stringify(record()),
    '2026-01-01',
  );
  db.prepare('INSERT INTO pipeline_entries VALUES(42,?,?)').run('Applying', 'Keep this staff note');
  db.close();
  const result = await importPython(store, file);
  assert.equal(result.grants, 1);
  const s = await store.read();
  assert.equal(s.grants[0].id, 42);
  assert.equal(s.grants[0].pipeline.notes, 'Keep this staff note');
  assert.equal(s.schedule.enabled, false);
  await assert.rejects(() => importPython(store, file), /unused/);
  const original = new DatabaseSync(file, { readOnly: true });
  assert.equal(
    original.prepare('SELECT notes FROM pipeline_entries').get().notes,
    'Keep this staff note',
  );
  original.close();
});
