import { views, filterGrants } from '../service.js';
import * as ui from '../views.js';

// CSV cells neutralize spreadsheet formulas before exporting user-controlled text.
export function registerExportRoutes(app, { send, fresh }) {
  app.get('/export.csv', async (req, res) => {
    const s = await fresh(),
      items = filterGrants(views(s), req.query);
    const cell = (v) =>
      '"' +
      String(v ?? '')
        .replace(/^[\s]*[=+@\-\t\r]/, (m) => "'" + m)
        .replaceAll('"', '""') +
      '"';
    const rows = [
      [
        'Title',
        'Funder',
        'Fit score',
        'Eligibility',
        'Confidence',
        'Deadline',
        'Source URL',
        'Stage',
        'Assignee',
        'Requested amount',
        'Staff deadline',
        'Submission date',
        'Notes',
        'Final result',
      ],
      ...items.map((g) => [
        g.record.grant_title,
        g.record.funder_name,
        g.assessment.fit_score,
        g.assessment.eligibility_status,
        g.assessment.confidence_score,
        g.record.deadline,
        g.record.source_url,
        g.pipeline?.status || 'Discovered',
        g.pipeline?.assigned_to,
        g.pipeline?.requested_amount,
        g.pipeline?.application_deadline,
        g.pipeline?.submission_date,
        g.pipeline?.notes,
        g.pipeline?.final_result,
      ]),
    ];
    res
      .attachment('grantiq.csv')
      .type('text/csv')
      .send('\uFEFF' + rows.map((r) => r.map(cell).join(',')).join('\r\n'));
  });
}
