import { reviewFields } from '../matching.js';
import { esc, input, textarea, select, form } from './html.js';

// Field kinds come from the same reviewFields contract used by server validation.
function factControl(key, type, value) {
  if (type === 'list' || type === 'text') return textarea(key, value);
  if (type === 'bool')
    return select(key, value === null ? 'unknown' : value ? 'yes' : 'no', ['unknown', 'yes', 'no']);
  if (type === 'scope')
    return select(key, value, ['unknown', 'local', 'state', 'regional', 'national']);
  if (type === 'status')
    return select(key, value, ['unknown', 'posted', 'forecasted', 'closed', 'archived']);
  return input(
    key,
    value,
    ['number', 'date', 'url'].includes(type) ? type : 'text',
    type === 'number' ? 'min="0" step="0.01"' : '',
  );
}

export function verification(g, token) {
  return /* HTML */ `<p>
      Confirm only facts you have checked against official evidence. Scores and eligibility verdicts
      cannot be directly edited.
    </p>
    ${form(
      `/grants/${g.id}/verify`,
      token,
      /* HTML */ `<section class="panel">
        <div class="grid">
          ${input('reviewed_by', '', 'text', 'required')}${input(
            'evidence_url',
            '',
            'url',
            'required',
          )}${input('valid_until', '', 'date', 'required')}
        </div>
        ${textarea('evidence_note', '', 3)}
        <p>Select each fact to verify. The new review replaces previous verified fields.</p>
        ${reviewFields
          .map(
            ([k, title, type]) =>
              /* HTML */ `<details>
                <summary>
                  <label class="check"
                    ><input type="checkbox" name="fields" value="${k}" />${esc(title)}</label
                  >
                </summary>
                ${factControl(k, type, g.record[k])}
              </details>`,
          )
          .join('')}
      </section>`,
      'Save verified facts',
    )}${form(
      `/grants/${g.id}/verify/withdraw`,
      token,
      input('reviewed_by', '', 'text', 'required'),
      'Withdraw current verification',
    )}`;
}
