import path from 'node:path';
import { root } from './config.js';
let extractor, loading;
const cache = new Map();
export async function loadModel(download = false) {
  if (extractor) return extractor;
  if (!loading)
    loading = (async () => {
      const { pipeline, env } = await import('@huggingface/transformers');
      env.cacheDir =
        process.env.GRANTIQ_MODEL_CACHE ||
        path.join(process.env.GRANTIQ_NODE_DATA_DIR || path.join(root, 'data/node'), 'models');
      env.allowRemoteModels = download;
      env.backends.onnx.wasm.numThreads = 1;
      extractor = await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2', {
        dtype: 'fp32',
        device: 'cpu',
        local_files_only: !download,
        session_options: { intraOpNumThreads: 1, interOpNumThreads: 1 },
      });
      return extractor;
    })().catch((e) => {
      loading = null;
      throw e;
    });
  return loading;
}
async function vector(text) {
  if (cache.has(text)) return cache.get(text);
  const model = await loadModel();
  const v = Array.from((await model(text, { pooling: 'mean', normalize: true })).data);
  if (cache.size >= 256) cache.delete(cache.keys().next().value);
  cache.set(text, v);
  return v;
}
let lastError = '';
export function modelStatus() {
  return {
    mode: process.env.GRANTIQ_SEMANTIC_MODE === 'local' ? 'local_requested' : 'keyword_fallback',
    ready: !!extractor,
    error: lastError,
  };
}
export async function semantic(g, p) {
  if (process.env.GRANTIQ_SEMANTIC_MODE !== 'local') return {};
  try {
    const a = await vector(
      [p.mission, p.description, ...p.programs, ...p.funding_interests].join('. '),
    );
    const b = await vector(
      [g.grant_title, g.description, ...g.program_areas, ...g.categories].join('. '),
    );
    const similarity = a.reduce((sum, v, i) => sum + v * b[i], 0);
    if (!Number.isFinite(similarity)) throw new Error('Nonfinite embedding result');
    lastError = '';
    return { similarity, mode: 'local_transformers_js' };
  } catch (e) {
    lastError = e.message;
    return {};
  }
}
if (process.argv.includes('--download')) {
  await loadModel(true);
  const sample = await extractor('Vision care and eye health', {
    pooling: 'mean',
    normalize: true,
  });
  if (sample.data.length !== 384 || ![...sample.data].every(Number.isFinite))
    throw new Error('Invalid MiniLM smoke result');
  console.log('Ready: MiniLM, 384 dimensions. Set GRANTIQ_SEMANTIC_MODE=local to enable.');
}
