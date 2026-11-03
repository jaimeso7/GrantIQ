// Escape untrusted values before inserting them into server-rendered HTML.
// Form content and extra attributes must be code-owned markup.
export const esc = (v) =>
  String(v ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  );
export const money = (v) =>
  v === null || v === undefined
    ? 'Unknown'
    : new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: 0,
      }).format(v);
const label = (k) =>
  ({ q: 'Search grants', min_score: 'Minimum fit score' })[k] ||
  k.replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase());
export const input = (key, value = '', type = 'text', extra = '') =>
  `<label>${esc(label(key))}<input name="${esc(key)}" type="${type}" value="${esc(value)}" ${extra}></label>`;
export const textarea = (key, value = '', rows = 4) =>
  `<label>${esc(label(key))}<textarea name="${esc(key)}" rows="${rows}">${esc(Array.isArray(value) ? value.join('\n') : value)}</textarea></label>`;
export const select = (key, value, options) =>
  `<label>${esc(label(key))}<select name="${esc(key)}">${options.map((v) => `<option value="${esc(v)}" ${String(v) === String(value) ? 'selected' : ''}>${esc(v || 'Any')}</option>`).join('')}</select></label>`;
export const csrf = (token) => `<input type="hidden" name="_csrf" value="${esc(token)}">`;
export const form = (url, token, content, button = 'Save') =>
  `<form method="post" action="${esc(url)}">${csrf(token)}${content}<button class="button button-primary" type="submit">${esc(button)}</button></form>`;
