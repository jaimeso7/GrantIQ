import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { profileSchema, grantSchema } from '../validation.js';
import { createStore, initialState } from '../store.js';
import { configuration } from '../config.js';
export const profile = () =>
  profileSchema.parse({
    name: 'Example charity',
    mission: 'Vision care and preventive health for children',
    programs: ['vision screening'],
    service_locations: ['Duval County, Florida'],
    populations_served: ['children'],
    funding_interests: ['eye health'],
  });
export const record = (overrides = {}) =>
  grantSchema.parse({
    source: 'Test',
    source_id: '1',
    source_url: 'https://example.org/grant',
    grant_title: 'Vision care for children',
    funder_name: 'Example Foundation',
    description: 'Vision screening and preventive eye health',
    eligibility_text: '501(c)(3) nonprofit organizations are eligible.',
    applicant_types: ['501(c)(3) nonprofits'],
    geographic_restrictions: ['Florida'],
    geography_scope: 'state',
    populations_served: ['children'],
    program_areas: ['vision screening'],
    award_min: 5000,
    award_max: 10000,
    deadline: '2099-12-31',
    grant_status: 'posted',
    ...overrides,
  });
export function seed() {
  const s = initialState();
  s.profile = profile();
  s.prospects = [];
  s.sources = [];
  s.schedule.enabled = false;
  return s;
}
export async function tempStore(t, extra = {}) {
  const dataDir = await fs.mkdtemp(path.join(os.tmpdir(), 'grantiq-node-'));
  const config = { ...configuration({}), dataDir, scheduler: false, ...extra };
  const store = await createStore(config, seed);
  t.after(async () => {
    await store.close();
    await fs.rm(dataDir, { recursive: true, force: true });
  });
  return { store, config, dataDir };
}
