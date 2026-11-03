import { z } from 'zod';
export const weights = {
  mission: 30,
  geography: 20,
  population: 15,
  funding: 10,
  program: 10,
  past_giving: 10,
  readiness: 5,
};
const text = z.string().max(100000),
  list = z.array(text).max(2000).default([]);
const amount = z.number().finite().nonnegative().nullable().default(null);
const bool = z.boolean().nullable().default(null);
export const httpUrl = z
  .string()
  .max(4096)
  .refine((v) => {
    try {
      const u = new URL(v);
      return ['http:', 'https:'].includes(u.protocol) && !u.username && !u.password;
    } catch {
      return false;
    }
  }, 'Use an HTTP(S) URL without credentials.');
export const date = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}$/)
  .refine(
    (v) => !isNaN(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v,
    'Invalid date',
  );
export const profileSchema = z
  .object({
    name: text.default('Vision Is Priceless'),
    organization_type: text.default('501(c)(3)'),
    mission: text.default(''),
    description: text.default(''),
    service_locations: list,
    populations_served: list,
    programs: list,
    funding_interests: list,
    ein: text.default(''),
    minimum_desired_award: z.number().finite().nonnegative().default(5000),
    maximum_desired_award: amount,
    annual_budget: amount,
    minimum_days_to_apply: z.number().int().min(0).max(365).default(7),
    matching_funds_available: bool,
    has_fiscal_sponsor: bool,
    invited_by_funders: list,
    existing_funder_relationships: list,
    excluded_funders: list,
    weights: z
      .object(
        Object.fromEntries(Object.keys(weights).map((k) => [k, z.number().finite().nonnegative()])),
      )
      .strict()
      .default(weights),
    readiness_thresholds: z.array(z.number().int().nonnegative()).length(3).default([45, 30, 15]),
    profile_source_url: httpUrl.nullable().default(null),
  })
  .refine(
    (p) => Math.abs(Object.values(p.weights).reduce((a, b) => a + b, 0) - 100) < 0.01,
    'Seven weights must total 100.',
  )
  .refine(
    (p) => p.maximum_desired_award === null || p.maximum_desired_award >= p.minimum_desired_award,
    'Maximum award must be at least the minimum.',
  )
  .refine(
    (p) =>
      p.readiness_thresholds[0] > p.readiness_thresholds[1] &&
      p.readiness_thresholds[1] > p.readiness_thresholds[2],
    'Readiness thresholds must decrease.',
  );
export const grantSchema = z
  .object({
    source: text,
    source_id: text,
    source_url: httpUrl,
    application_url: httpUrl.nullable().default(null),
    grant_title: text.min(1),
    funder_name: text.default('Unknown'),
    description: text.default(''),
    eligibility_text: text.default(''),
    applicant_types: list,
    geographic_restrictions: list,
    geography_scope: z
      .enum(['local', 'state', 'regional', 'national', 'unknown'])
      .default('unknown'),
    populations_served: list,
    categories: list,
    program_areas: list,
    award_min: amount,
    award_max: amount,
    estimated_award: amount,
    open_date: date.nullable().default(null),
    deadline: date.nullable().default(null),
    deadline_text: text.default(''),
    grant_status: z
      .enum(['posted', 'forecasted', 'closed', 'archived', 'unknown'])
      .default('unknown'),
    application_requirements: list,
    contact_information: text.default(''),
    loi_required: bool,
    application_stages: list,
    invitation_only: bool,
    matching_funds_required: bool,
    fiscal_sponsor_required: bool,
    existing_relationship_required: bool,
    budget_min: amount,
    budget_max: amount,
    past_giving: z.array(z.record(z.string(), z.unknown())).default([]),
    last_checked: text.default(() => new Date().toISOString()),
    raw_text: text.default(''),
    warnings: list,
    is_demo: z.boolean().default(false),
  })
  .refine(
    (g) => g.award_min === null || g.award_max === null || g.award_min <= g.award_max,
    'Invalid award range.',
  )
  .refine(
    (g) => g.budget_min === null || g.budget_max === null || g.budget_min <= g.budget_max,
    'Invalid budget range.',
  );
export const statuses = [
  'Discovered',
  'Reviewing',
  'Interested',
  'Applying',
  'Submitted',
  'Awarded',
  'Rejected',
  'Skipped',
];
export const pipelineSchema = z.object({
  status: z.enum(statuses),
  notes: text.default(''),
  assigned_to: z.string().max(200).default(''),
  requested_amount: amount,
  application_deadline: date.nullable().default(null),
  submission_date: date.nullable().default(null),
  final_result: text.default(''),
});
export const lines = (v) =>
  String(v || '')
    .split(/\r?\n/)
    .map((x) => x.trim())
    .filter(Boolean);
export const number = (v) => (v === '' || v === undefined || v === null ? null : Number(v));
export const triBool = (v) => (v === 'yes' ? true : v === 'no' ? false : null);
