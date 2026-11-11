import { score as legacyScore, overlap } from './matching.js';

// Versioned policy: keep imported profiles intact, but use the grant-watch rubric
// for new assessments. The legacy scorer supplies tested eligibility/geography gates.
export const rubricVersion = 'grant-watch-1';
export const rubric = {
  mission: ['Mission / program alignment', 25],
  geography: ['Geographic eligibility', 20],
  population: ['Populations served', 15],
  purpose: ['Funding purpose / eligible expenses', 15],
  accessibility: ['Application accessibility', 10],
  value: ['Potential funding value', 10],
  timing: ['Timing / feasibility', 5],
};

export function applicationPath(g) {
  const route =
    g.invitation_only === true
      ? 'Invitation / relationship development'
      : g.loi_required === true
        ? 'Letter of inquiry before full application'
        : g.application_url
          ? 'Review guidelines and application portal'
          : 'Application route not verified';
  const barriers = [
    g.invitation_only === true && 'Invitation required',
    g.existing_relationship_required === true && 'Existing relationship required',
    g.matching_funds_required === true && 'Matching funds required',
    g.fiscal_sponsor_required === true && 'Fiscal sponsor required',
  ].filter(Boolean);
  return {
    route,
    barriers,
    stages: g.application_stages,
    effort: 'Not verified — review required documents, approvals and preparation time with staff.',
    next:
      g.invitation_only === true
        ? 'Confirm an eligible introduction or inquiry route before preparing an application.'
        : g.loi_required === true
          ? 'Verify the LOI deadline, required attachments and invitation process.'
          : 'Verify current eligibility, eligible expenses and cycle on the official source before applying.',
  };
}

export function watchScore(g, p, options = {}) {
  const base = legacyScore(
    g,
    {
      ...p,
      weights: {
        mission: 25,
        geography: 20,
        population: 15,
        funding: 10,
        program: 15,
        past_giving: 10,
        readiness: 5,
      },
    },
    options,
  );
  const old = Object.fromEntries(base.components.map((c) => [c.key, c]));
  const failed = base.eligibility_status === 'Ineligible';
  const purposeText = [...g.program_areas, ...g.categories, ...g.application_requirements].join(
    ' ',
  );
  // Absence of restrictions is not evidence that operating or staffing expenses qualify.
  const purpose = purposeText.trim() ? overlap(p.funding_interests.join(' '), purposeText) : 0;
  const accessible = base.eligibility_status === 'Eligible' && !!g.application_url;
  const fractions = {
    value: [
      [g.award_min, g.award_max, g.estimated_award].some((v) => v !== null)
        ? old.funding.points / 10
        : 0,
      'Reported award value compared with the organization’s funding range; unknown awards receive no points.',
    ],
    timing: [
      g.grant_status === 'posted' ? old.readiness.points / 5 : 0,
      g.grant_status === 'posted'
        ? old.readiness.explanation
        : 'Current opening not verified; no timing points.',
    ],
    purpose: [
      purpose,
      purposeText
        ? 'Overlap with reported funding purposes; confirm specific eligible expenses.'
        : 'Eligible expenses not verified; no points awarded.',
    ],
    accessibility: [
      accessible
        ? g.invitation_only || g.existing_relationship_required
          ? 0.3
          : g.loi_required
            ? 0.8
            : 1
        : 0,
      accessible
        ? applicationPath(g).route
        : 'Eligibility or application route not verified; no points awarded.',
    ],
  };
  const aliases = { value: 'funding', timing: 'readiness' };
  const components = Object.entries(rubric).map(([key, [label, maximum]]) => {
    const previous = old[aliases[key] || key];
    const points = fractions[key] ? fractions[key][0] * maximum : previous.points;
    return {
      key,
      label,
      maximum,
      points: failed ? 0 : Math.round(points * 100) / 100,
      explanation: failed
        ? 'Not awarded: eligibility gate failed.'
        : fractions[key]?.[1] || previous.explanation,
    };
  });
  const fit_score = Math.round(components.reduce((n, c) => n + c.points, 0) * 100) / 100;
  const priority =
    fit_score >= 90
      ? 'Exceptional Fit'
      : fit_score >= 75
        ? 'Strong Fit'
        : fit_score >= 60
          ? 'Moderate Fit'
          : 'Lower Priority';
  const provisional = base.eligibility_status !== 'Eligible';
  return {
    ...base,
    components,
    fit_score,
    rubric_version: rubricVersion,
    priority,
    provisional,
    recommendation: failed ? 'INELIGIBLE' : `${priority}${provisional ? ' (provisional)' : ''}`,
    match_explanation: components.map(
      (c) => `${c.label}: ${c.points}/${c.maximum}. ${c.explanation}`,
    ),
    application_path: applicationPath(g),
  };
}
