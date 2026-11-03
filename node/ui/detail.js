import { esc } from './html.js';
import { card, pipelineForm } from './discovery.js';

export function detail(g, token) {
  const r = g.record,
    a = g.assessment;
  return /* HTML */ `<p><a href="/">← Discover</a></p>
    ${card(g)}
    <section class="panel">
      <h2>Source and evidence</h2>
      <p>
        <a href="${esc(r.source_url)}" target="_blank" rel="noopener noreferrer">Official source</a
        >${r.application_url
          ? ` · <a href="${esc(r.application_url)}" target="_blank" rel="noopener noreferrer">Application page</a>`
          : ''}
      </p>
      <p>
        Last checked: ${esc(r.last_checked)} · Scoring mode:
        <strong>${esc(a.semantic_mode)}</strong>
      </p>
      <p>${esc(r.description)}</p>
      <h3>Eligibility text</h3>
      <p>${esc(r.eligibility_text || 'Not provided')}</p>
      <p>Verification: ${esc(g.state)}</p>
      <a href="/grants/${g.id}/verify">Verify source facts</a>
      <ul>
        ${a.warnings.map((w) => /* HTML */ `<li>${esc(w)}</li>`).join('')}
      </ul>
    </section>
    <section class="panel">
      <h2>Why this score?</h2>
      <table>
        <thead>
          <tr>
            <th>Component</th>
            <th>Points</th>
            <th>Explanation</th>
          </tr>
        </thead>
        <tbody>
          ${a.components
            .map(
              (c) =>
                /* HTML */ `<tr>
                  <td>${esc(c.label)}</td>
                  <td>${c.points}/${c.maximum}</td>
                  <td>${esc(c.explanation)}</td>
                </tr>`,
            )
            .join('')}
        </tbody>
      </table>
      <h3>Eligibility checks</h3>
      <ul>
        ${a.eligibility_checks
          .map(
            (c) => /* HTML */ `<li><strong>${esc(c.outcome)}</strong> · ${esc(c.explanation)}</li>`,
          )
          .join('')}
      </ul>
    </section>
    <section class="panel">
      <h2>Team pipeline</h2>
      ${pipelineForm(g, token)}
    </section>
    <section class="panel">
      <h2>Application requirements</h2>
      <ul>
        ${r.application_requirements.map((v) => /* HTML */ `<li>${esc(v)}</li>`).join('') ||
        '<li>Review official announcement.</li>'}
      </ul>
      <p>${esc(r.contact_information)}</p>
      <h3>Source history</h3>
      <ul>
        ${g.sources
          .map(
            (v) =>
              /* HTML */ `<li>
                <a href="${esc(v.source_url)}">${esc(v.source)}</a> · ${esc(v.last_checked)}
              </li>`,
          )
          .join('')}
      </ul>
      <h3>Verification history</h3>
      ${g.reviews
        .map(
          (v) =>
            /* HTML */ `<p>
              ${esc(v.action)} · ${esc(v.reviewed_by)} · ${esc(v.reviewed_at)} ·
              ${esc(v.evidence_note)} <a href="${esc(v.evidence_url)}">Evidence</a>
            </p>`,
        )
        .join('') || '<p>No staff verifications yet.</p>'}
    </section>`;
}
