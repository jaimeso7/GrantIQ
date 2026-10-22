import { configuration } from '../config.js';
import { createStore } from '../store.js';
import { createDiscovery } from '../service.js';
const config = configuration();
const store = await createStore(config);
try {
  const discovery = createDiscovery(store, config);
  const ran = await discovery.run();
  const run = (await store.read()).runs.at(-1);
  console.log(JSON.stringify(run, null, 2));
  if (!ran || run.status !== 'success') process.exitCode = 1;
} finally {
  await store.close();
}
