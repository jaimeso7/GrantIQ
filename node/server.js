import { configuration } from './config.js';
import { createStore } from './store.js';
import { createDiscovery } from './service.js';
import { createApp } from './app.js';
const config = configuration();
const store = await createStore(config);
const discovery = createDiscovery(store, config);
const app = createApp(store, config, discovery);
const server = app.listen(config.port, config.host, () => {
  console.log(`GrantIQ Node listening on ${config.host}:${config.port}`);
  discovery.start();
});
let closing = false;
async function shutdown() {
  if (closing) return;
  closing = true;
  await Promise.all([new Promise((resolve) => server.close(resolve)), discovery.stop()]);
  await store.close();
  process.exit(0);
}
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
server.on('error', async (error) => {
  console.error(error.message);
  await store.close();
  process.exitCode = 1;
});
