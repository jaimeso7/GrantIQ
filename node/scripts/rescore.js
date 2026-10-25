import { configuration } from '../config.js';
import { createStore } from '../store.js';
import { rescore } from '../service.js';
const store = await createStore(configuration());
try {
  await store.update(rescore);
  console.log(
    'Existing opportunities rescored using the current profile and available matching model.',
  );
} finally {
  await store.close();
}
