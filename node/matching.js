import fs from 'node:fs';
import { createHash } from 'node:crypto';
import { today, now, researchFile } from './store.js';
import { grantSchema, httpUrl } from './validation.js';
const C = JSON.parse(fs.readFileSync(new URL('./constants.json', import.meta.url), 'utf8'));
export const reviewFields = C.REVIEW_FIELDS;
export const normalize = (v) =>
  String(v || '')
    .toLowerCase()
    .replaceAll('saint ', 'st ')
    .replaceAll('northeastern', 'northeast')
    .replace(/[^a-z0-9\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
const phrase = (v, p) => !!normalize(p) && ` ${normalize(v)} `.includes(` ${normalize(p)} `);
const intersect = (a, b) => [...a].some((v) => b.has(v));
const counties = (v) => {
  const a = C.FL_COUNTIES.filter((c) => phrase(v, `${c} county`));
  return new Set(
    a.length
      ? a
      : [...String(v).matchAll(/(?:^|,|;|\band\b)\s*([A-Za-z. -]+?)\s+County\b/gi)].map((m) =>
          normalize(m[1]),
        ),
  );
};
const states = (v) => {
  const clean = normalize(v);
  const a = new Set(Object.values(C.STATE_NAMES).filter((s) => phrase(clean, s)));
  for (const t of clean.split(' ')) if (C.STATE_NAMES[t]) a.add(C.STATE_NAMES[t]);
  if (!a.size && [...counties(v)].some((c) => C.FL_COUNTIES.includes(c))) a.add('florida');
  return a;
};
const stateOnly = (v) =>
  !!C.STATE_NAMES[normalize(v)] ||
  Object.values(C.STATE_NAMES).includes(normalize(v).replace(/^state of /, ''));
const match = (outcome, fraction, explanation) => ({ outcome, fraction, explanation });
export function geography(g, p) {
  if (!p.service_locations.length)
    return match('review', 0.25, 'Organization service locations have not been configured.');
  let restrictions = g.geographic_restrictions.filter(
    (x) => !['unknown', 'unspecified', ''].includes(normalize(x)),
  );
  if (!restrictions.length)
    for (const sentence of g.eligibility_text.split(/[.;\n]/))
      if (/\b(only|exclusively|restricted to|must (?:be|operate)|limited to)\b/i.test(sentence))
        restrictions.push(...Object.values(C.STATE_NAMES).filter((s) => phrase(sentence, s)));
  const os = new Set(p.service_locations.flatMap((v) => [...states(v)])),
    oc = new Set(p.service_locations.flatMap((v) => [...counties(v)])),
    clean = new Set(p.service_locations.map(normalize));
  for (const s of os)
    if (
      new RegExp(
        `(?:excluding|except(?: for)?|not available (?:in|to))\\s+(?:organizations (?:in|from)\\s+)?${s}\\b`,
      ).test(normalize(g.eligibility_text))
    )
      return match('fail', 0, `Eligibility explicitly excludes ${s}.`);
  if (
    g.geography_scope === 'national' ||
    restrictions.some((v) => C.NATIONAL.includes(normalize(v)))
  )
    return os.size || [...clean].some((v) => C.NATIONAL.includes(v))
      ? match('pass', 0.5, 'National U.S. opportunity covers the configured service area.')
      : match('review', 0.25, 'Confirm the organization country eligibility.');
  if (!restrictions.length)
    return match('review', 0.25, 'Geographic eligibility is not confirmed by the source.');
  let uncertain = false;
  for (const target of restrictions) {
    const tc = counties(target),
      ts = states(target);
    if (tc.size) {
      if (intersect(tc, oc)) {
        if (ts.size && os.size && !intersect(ts, os)) continue;
        return match('pass', 1, `Explicit county coverage: ${target}.`);
      }
      if (!oc.size || !ts.size) uncertain = true;
      continue;
    }
    if (clean.has(normalize(target)))
      return match(
        'pass',
        stateOnly(target) ? 0.85 : g.geography_scope === 'regional' ? 0.7 : 1,
        `The source explicitly covers ${target}.`,
      );
    if (stateOnly(target)) {
      if (intersect(ts, os)) return match('pass', 0.85, `Statewide coverage includes ${target}.`);
      if (!os.size) uncertain = true;
    } else uncertain = true;
  }
  return uncertain
    ? match('review', 0.25, `Confirm coverage against: ${restrictions.join('; ')}.`)
    : match('fail', 0, 'The stated geography does not include the configured service locations.');
}
function applicant(g, p) {
  const org = normalize(p.organization_type),
    t = normalize(g.eligibility_text),
    nonprofit = /501 c 3|501c3|nonprofit|non profit/.test(org);
  if (
    nonprofit &&
    (/(?:nonprofits?(?: organizations?)?|non profit organizations?|501 c 3(?: organizations?)?) (?:are |is )?(?:not eligible|ineligible|excluded|not permitted)/.test(
      t,
    ) ||
      /(?:excludes?|excluding|does not fund|not open to) (?:all )?(?:nonprofits?|non profit organizations?|501 c 3)/.test(
        t,
      ))
  )
    return ['fail', 'Source explicitly excludes nonprofit applicants.'];
  if (
    /(?:government|governmental|public agenc|state agenc|municipalit)[a-z ]{0,35}\bonly\b|\bonly\b[a-z ]{0,25}(?:government|governmental|public agencies)|(?:restricted|limited) to (?:state and local )?(?:government|governmental|public agenc)/.test(
      t,
    ) &&
    !/(government|municipal|public agency)/.test(org)
  )
    return ['fail', 'Government applicants only.'];
  if (
    /(?:universities|university|institutions of higher education|colleges)[a-z ]{0,18}\bonly\b|\bonly\b[a-z ]{0,18}(?:universities|institutions of higher education)|(?:restricted|limited) to (?:public |private )?(?:universities|institutions of higher education)/.test(
      t,
    ) &&
    !/(university|college|higher education)/.test(org)
  )
    return ['fail', 'Higher-education applicants only.'];
  const types = g.applicant_types.map(normalize);
  if (!types.length) {
    if (
      nonprofit &&
      /(?:501 c 3|501c3|nonprofit|non profit)[a-z0-9 ]{0,30}(?:eligible|may apply|can apply)|(?:eligible applicants|open to|for) (?:include )?(?:501 c 3|nonprofit)/.test(
        t,
      )
    )
      return ['pass', 'Eligibility accepts nonprofits.'];
    return ['review', 'Applicant type unconfirmed.'];
  }
  if (
    types.some((v) => ['unrestricted', 'all', 'any organization', 'all entity types'].includes(v))
  )
    return ['pass', 'Applicant types unrestricted.'];
  if (
    nonprofit &&
    types.some((v) => /nonprofit|non profit|501 c 3|501c3/.test(v) && !v.includes('without'))
  )
    return ['pass', 'Nonprofit applicants explicitly listed.'];
  if (org && types.includes(org)) return ['pass', 'Organization type listed.'];
  if (
    types.every((v) =>
      /government|university|universities|higher education|school district|individual|for profit|small business|tribal|public housing/.test(
        v,
      ),
    )
  )
    return ['fail', 'Restricted applicant list does not include this organization.'];
  return ['review', 'Confirm applicant-type eligibility.'];
}
export const daysUntil = (date, day = today()) =>
  Math.round((Date.parse(date) - Date.parse(day)) / 86400000);
const rolling = (g) =>
  /\b(rolling|ongoing|year round|no deadline)\b/.test(normalize(g.deadline_text));
export function eligibility(g, p, day = today()) {
  const checks = [];
  const add = (key, outcome, explanation) =>
    checks.push({ key, outcome, status: outcome, explanation });
  add('organization_type', ...applicant(g, p));
  const geo = geography(g, p);
  add('geography', geo.outcome, geo.explanation);
  if (['closed', 'archived'].includes(g.grant_status) || (g.deadline && g.deadline < day))
    add('deadline', 'fail', 'Opportunity is closed, archived, or past deadline.');
  else if (g.grant_status === 'forecasted' || g.open_date > day)
    add('deadline', 'review', 'Applications are not yet confirmed open.');
  else if (!g.deadline)
    add(
      'deadline',
      rolling(g) && g.grant_status === 'posted' ? 'pass' : 'review',
      rolling(g) && g.grant_status === 'posted'
        ? 'Open rolling deadline.'
        : 'Current deadline unconfirmed.',
    );
  else if (daysUntil(g.deadline, day) < p.minimum_days_to_apply)
    add('deadline', 'review', 'Less than the configured preparation time remains.');
  else
    add(
      'deadline',
      g.grant_status === 'unknown' ? 'review' : 'pass',
      g.grant_status === 'unknown'
        ? 'Application status unconfirmed.'
        : `${daysUntil(g.deadline, day)} days remain.`,
    );
  if (g.award_max !== null && g.award_max < p.minimum_desired_award)
    add('award', 'fail', 'Maximum award is below your minimum.');
  else if (
    p.maximum_desired_award !== null &&
    g.award_min !== null &&
    g.award_min > p.maximum_desired_award
  )
    add('award', 'fail', 'Minimum award exceeds your maximum.');
  else
    add(
      'award',
      [g.award_min, g.award_max, g.estimated_award].every((v) => v === null) ? 'review' : 'pass',
      [g.award_min, g.award_max, g.estimated_award].every((v) => v === null)
        ? 'Award amounts unknown.'
        : 'Known award information fits funding limits.',
    );
  const t = normalize([g.eligibility_text, ...g.application_requirements].join(' ')),
    f = normalize(g.funder_name);
  const conditions = [
    [
      'invitation',
      g.invitation_only,
      /\b(invitation only|invite only|by invitation|must be invited)\b/,
      p.invited_by_funders.map(normalize).includes(f),
    ],
    [
      'matching_funds',
      g.matching_funds_required,
      /(?:matching funds|cost shar(?:e|ing)|match) (?:is |are )?required|requires? (?:a )?(?:match|matching funds|cost shar)/,
      p.matching_funds_available,
    ],
    [
      'fiscal_sponsor',
      g.fiscal_sponsor_required,
      /(?:fiscal sponsor|fiscal sponsorship) (?:is )?required|must have a fiscal sponsor/,
      p.has_fiscal_sponsor,
    ],
    [
      'existing_relationship',
      g.existing_relationship_required,
      /existing (?:funder )?relationship (?:is )?required|previous (?:grantees|recipients) only/,
      p.existing_funder_relationships.map(normalize).includes(f),
    ],
  ];
  for (const [key, flag, re, confirmed] of conditions)
    if (flag === true || re.test(t))
      add(
        key,
        confirmed === true
          ? 'pass'
          : confirmed === false && ['matching_funds', 'fiscal_sponsor'].includes(key)
            ? 'fail'
            : 'review',
        confirmed === true
          ? 'Required condition confirmed.'
          : `Required ${key.replaceAll('_', ' ')} not confirmed.`,
      );
  if (g.budget_min !== null || g.budget_max !== null)
    add(
      'budget',
      p.annual_budget === null
        ? 'review'
        : (g.budget_min !== null && p.annual_budget < g.budget_min) ||
            (g.budget_max !== null && p.annual_budget > g.budget_max)
          ? 'fail'
          : 'pass',
      'Check organization budget against the stated limits.',
    );
  else if (
    /\b(?:annual|operating|organization) budget\b.{0,50}\b(?:under|over|less than|greater than|minimum|maximum)\b/.test(
      t,
    )
  )
    add('budget', 'review', 'Source describes a budget restriction requiring review.');
  if (/\b(?:religious|faith based|church)\b/.test(t))
    add('religious_restrictions', 'review', 'Review religious-activity conditions.');
  if (
    /\b(?:only|exclusively|restricted to|must serve)\b.{0,80}\b(?:children|adults|veterans|seniors|women|youth|research|capital|schools|programs)\b/.test(
      t,
    )
  )
    add(
      'population_program_restrictions',
      'review',
      'Review explicit population/program restrictions.',
    );
  if (!p.mission.trim() || !p.programs.length)
    add('profile', 'review', 'Complete organization mission and programs.');
  if (!g.eligibility_text.trim())
    add('source_requirements', 'review', 'Detailed eligibility text missing.');
  let status = checks.some((c) => c.outcome === 'fail')
    ? 'Ineligible'
    : checks.some((c) => c.outcome === 'review')
      ? 'Needs Review'
      : 'Likely Eligible';
  if (
    status === 'Likely Eligible' &&
    [
      g.invitation_only,
      g.matching_funds_required,
      g.fiscal_sponsor_required,
      g.existing_relationship_required,
    ].every((v) => typeof v === 'boolean')
  )
    status = 'Eligible';
  return {
    status,
    checks,
    warnings: checks.filter((c) => c.outcome !== 'pass').map((c) => c.explanation),
  };
}
const tokens = (t) =>
  new Set(
    normalize(t)
      .split(' ')
      .filter((v) => v.length > 2 && !C.STOP_WORDS.includes(v))
      .map((v) => C.SYNONYMS[v] || v),
  );
export function overlap(a, b) {
  const x = tokens(a),
    y = tokens(b);
  return Math.min(x.size, y.size)
    ? [...x].filter((v) => y.has(v)).length / Math.min(x.size, y.size)
    : 0;
}
const clamp = (v) => Math.max(0, Math.min(1, v));
export function confidence(g) {
  return (
    10 * !!g.eligibility_text.trim() +
    10 * !!g.applicant_types.length +
    15 * !!(g.geographic_restrictions.length || g.geography_scope === 'national') +
    15 * !!(g.deadline || rolling(g)) +
    15 * [g.award_min, g.award_max, g.estimated_award].some((v) => v !== null) +
    15 * !!(g.program_areas.length || g.categories.length) +
    10 * !!g.application_url +
    10 * !['', 'unknown', 'not specified'].includes(normalize(g.funder_name))
  );
}
export function score(g, p, { day = today(), similarity = null, mode = 'keyword_fallback' } = {}) {
  const e = eligibility(g, p, day),
    warnings = [...g.warnings, ...e.warnings];
  const org = [p.mission, p.description, ...p.programs, ...p.funding_interests].join('. '),
    offered = [g.grant_title, g.description, ...g.program_areas, ...g.categories].join('. ');
  const keyword = overlap(org, offered);
  if (!Number.isFinite(similarity)) {
    similarity = null;
    mode = 'keyword_fallback';
  }
  let funding = 0.4,
    fundingNote = 'Award unknown; no funding value invented.';
  if ([g.award_min, g.award_max, g.estimated_award].some((v) => v !== null)) {
    const likely = g.estimated_award ?? g.award_max ?? g.award_min;
    funding =
      (g.award_max !== null && g.award_max < p.minimum_desired_award) ||
      (p.maximum_desired_award !== null &&
        g.award_min !== null &&
        g.award_min > p.maximum_desired_award)
        ? 0
        : likely < p.minimum_desired_award ||
            (p.maximum_desired_award !== null && likely > p.maximum_desired_award)
          ? 0.7
          : g.award_min !== null && g.award_max !== null
            ? 1
            : 0.9;
    fundingNote = `Reported award range: ${g.award_min ?? 'unknown'} to ${g.award_max ?? 'unknown'}; typical ${g.estimated_award ?? 'unknown'}.`;
  }
  let history = 0;
  for (const v of g.past_giving)
    if (
      String(v.recipient_name || v.recipient || '').trim() &&
      httpUrl.safeParse(v.source_url || v.evidence_url || '').success
    )
      history = Math.max(
        history,
        overlap(
          [
            p.mission,
            ...p.programs,
            ...p.funding_interests,
            ...p.populations_served,
            ...p.service_locations,
          ].join(' '),
          [
            'description',
            'purpose',
            'program',
            'categories',
            'populations_served',
            'location',
            'geography',
          ]
            .map((k) => v[k] || '')
            .join(' '),
        ),
      );
  let readiness = 0,
    readinessNote = 'Closed or not yet confirmed open.';
  if (
    !['closed', 'archived', 'forecasted'].includes(g.grant_status) &&
    !(g.deadline && g.deadline < day) &&
    !(g.open_date > day)
  ) {
    const d = daysUntil(g.deadline, day),
      [long, medium, short] = p.readiness_thresholds;
    readiness = !g.deadline
      ? rolling(g) && g.grant_status === 'posted'
        ? 0.8
        : 0.2
      : d > long
        ? 1
        : d >= medium
          ? 0.8
          : d >= short
            ? 0.6
            : 0.2;
    readinessNote = g.deadline
      ? `${d} days remain.`
      : rolling(g)
        ? 'Confirm current rolling cycle.'
        : 'Deadline unknown.';
  }
  const geo = geography(g, p);
  const fractions = {
    mission: [
      0.35 * keyword + (similarity === null ? 0 : 0.65 * Math.max(0, Math.min(1, similarity))),
      similarity === null
        ? 'Keyword fallback: semantic share unavailable; capped at 35% of mission weight.'
        : `65% MiniLM cosine (${similarity.toFixed(3)}) + 35% keyword overlap.`,
    ],
    geography: [geo.fraction, geo.explanation],
    population: [
      g.populations_served.length && p.populations_served.length
        ? overlap(p.populations_served.join(' '), g.populations_served.join(' '))
        : 0.25,
      'Overlap of source populations; incomplete data receives uncertainty credit.',
    ],
    funding: [funding, fundingNote],
    program: [
      g.program_areas.length || g.categories.length
        ? overlap(
            [...p.programs, ...p.funding_interests].join(' '),
            [...g.program_areas, ...g.categories].join(' '),
          )
        : 0.2,
      'Overlap of supported programs; missing information receives uncertainty credit.',
    ],
    past_giving: [
      history,
      history
        ? 'Source-backed recipient details overlap the mission.'
        : 'No relevant, source-backed recipient evidence; zero points.',
    ],
    readiness: [readiness, readinessNote],
  };
  const fail = e.status === 'Ineligible';
  const components = Object.entries(p.weights).map(([key, maximum]) => ({
    key,
    label: C.LABELS[key],
    maximum,
    points: fail ? 0 : Math.round(clamp(fractions[key][0]) * maximum * 100) / 100,
    explanation: fail ? 'Not awarded: eligibility gate failed.' : fractions[key][1],
  }));
  const fit_score = Math.round(components.reduce((a, c) => a + c.points, 0) * 100) / 100;
  if (mode === 'keyword_fallback' && !fail)
    warnings.push(
      'Semantic matching unavailable; keyword-only mission scoring is capped at 35% of the mission weight.',
    );
  const label =
    fit_score >= 90
      ? 'Exceptional Match'
      : fit_score >= 80
        ? 'Strong Match'
        : fit_score >= 70
          ? 'Good Match'
          : fit_score >= 60
            ? 'Possible Match'
            : fit_score >= 40
              ? 'Low Priority'
              : 'Poor Match';
  return {
    fit_score,
    confidence_score: confidence(g),
    eligibility_status: e.status,
    recommendation: fail ? 'INELIGIBLE' : e.status === 'Needs Review' ? 'Needs Review' : label,
    components,
    match_explanation: components.map(
      (c) => `${c.label}: ${c.points}/${c.maximum}. ${c.explanation}`,
    ),
    warnings: [...new Set(warnings)],
    eligibility_checks: e.checks,
    semantic_similarity: fail ? null : similarity,
    semantic_mode: fail ? 'not_run_ineligible' : mode,
    scored_at: now(),
  };
}
const stable = (v) =>
  Array.isArray(v)
    ? v.map(stable)
    : v && typeof v === 'object'
      ? Object.fromEntries(
          Object.keys(v)
            .sort()
            .map((k) => [k, stable(v[k])]),
        )
      : v;
export const revision = (g) =>
  createHash('sha256')
    .update(
      JSON.stringify(
        stable(
          Object.fromEntries(
            Object.entries(g).filter(([k]) => !['last_checked', 'warnings'].includes(k)),
          ),
        ),
      ),
    )
    .digest('hex');
export function effective(item, day = today()) {
  let record = { ...item.record },
    state = 'none';
  const latest = item.reviews?.at(-1);
  if (latest) {
    state =
      latest.action === 'withdrawn'
        ? 'withdrawn'
        : latest.source_revision !== revision(record)
          ? 'source_changed'
          : latest.valid_until < day
            ? 'expired'
            : 'current';
    if (state === 'current')
      record = {
        ...record,
        ...latest.facts,
        warnings: [
          ...record.warnings,
          `Facts verified by ${latest.reviewed_by}; evidence ${latest.evidence_url}; expires ${latest.valid_until}.`,
        ],
      };
  }
  if (record.deadline && record.deadline < day && record.grant_status !== 'archived')
    record.grant_status = 'closed';
  return { record: grantSchema.parse(record), state };
}
export const funderKey = (v) =>
  normalize(
    String(v)
      .normalize('NFKD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/[&+]/g, ' and '),
  )
    .replace(/^the /, '')
    .replace(/ (inc|incorporated|llc)$/, '');
export function staffContext(item, s) {
  const excluded = new Set(s.profile.excluded_funders.map(funderKey));
  for (const f of (s.funderRegister || researchFile('existing_funders.json', { funders: [] }))
    .funders || [])
    if (excluded.has(funderKey(f.name)))
      for (const a of f.aliases || []) excluded.add(funderKey(a));
  const key = funderKey(item.record.funder_name);
  if (key && excluded.has(key))
    return {
      hidden: true,
      label: 'Staff excluded',
      reason: 'Organization preference, not an eligibility finding.',
    };
  const p = s.prospects.find(
    (p) =>
      [p.original.name, ...(p.original.aliases || [])].map(funderKey).includes(key) &&
      (!p.original.scope ||
        item.record.grant_title.toLowerCase().includes(p.original.scope.toLowerCase())),
  );
  if (!p) return null;
  const deferred = p.review_on > today();
  return {
    hidden: deferred || ['Do not pursue', 'Partner blocked'].includes(p.disposition),
    label: deferred ? 'Deferred by staff' : p.disposition,
    reason: [p.original.staff_note, p.team_notes, p.review_on ? `Staff review: ${p.review_on}` : '']
      .filter(Boolean)
      .join(' '),
  };
}
