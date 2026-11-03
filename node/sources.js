import * as cheerio from 'cheerio';
import robotsParser from 'robots-parser';
import { grantSchema, httpUrl } from './validation.js';
import { api, request, delay } from './network.js';
export const plain = (v) =>
  cheerio
    .load(`<body>${String(v ?? '')}</body>`)('body')
    .text()
    .replace(/\s+/g, ' ')
    .trim();
const first = (...xs) => xs.find((x) => x !== undefined && x !== null && x !== '');
const descriptions = (items) =>
  Array.isArray(items)
    ? [
        ...new Set(
          items
            .map((v) =>
              plain(typeof v === 'object' ? first(v.description, v.programTitle, v.name) : v),
            )
            .filter(Boolean),
        ),
      ]
    : [];
export function parseDate(v) {
  if (!v) return null;
  const s = String(v).trim();
  const iso = /^\d{4}-\d{2}-\d{2}/.exec(s)?.[0];
  if (iso && !isNaN(Date.parse(iso)) && new Date(iso).toISOString().slice(0, 10) === iso)
    return iso;
  if (/^\d{1,2}\/\d{1,2}\/\d{4}$/.test(s) || /^[a-z]+ \d{1,2}, \d{4}$/i.test(s)) {
    const d = new Date(s);
    if (!isNaN(d)) return d.toISOString().slice(0, 10);
  }
  return null;
}
export function parseAmount(v) {
  if (v === null || v === undefined || typeof v === 'boolean' || String(v).trim() === '')
    return null;
  const n = Number(String(v).replace(/[$,]/g, ''));
  return Number.isFinite(n) && n >= 0 ? n : null;
}
const link = (v) => (httpUrl.safeParse(v).success ? v : null);
export function normalizeFederal(raw) {
  const search = raw._search || {},
    syn = raw.synopsis || raw.forecast || {},
    id = String(first(raw.id, search.id, raw.opportunityId) || '');
  if (!/^\d+$/.test(id)) throw new Error('Opportunity requires a numeric ID.');
  const grant_title = plain(first(raw.opportunityTitle, raw.title, search.title));
  if (!grant_title) throw new Error('Missing opportunity title.');
  const description = plain(first(syn.synopsisDesc, syn.forecastDesc, raw.description));
  const applicant_types = descriptions(syn.applicantTypes),
    extra = plain(first(syn.applicantEligibilityDesc, syn.additionalInformationOnEligibility));
  const eligibility_text = [...applicant_types, ...(extra ? [extra] : [])].join('; ');
  let grant_status = String(first(search.oppStatus, raw.oppStatus, raw.ost) || '').toLowerCase();
  if (!['posted', 'forecasted', 'closed', 'archived'].includes(grant_status))
    grant_status = raw.forecast && !raw.synopsis ? 'forecasted' : 'unknown';
  let dv = first(
    syn.responseDateStr,
    syn.responseDate,
    syn.closeDate,
    search.closeDate,
    raw.closeDate,
  );
  let deadline_text = plain(first(syn.responseDateDesc, raw.originalDueDateDesc));
  const warnings = ['Geographic eligibility is unconfirmed; read the official announcement.'];
  if (!applicant_types.length) warnings.push('Applicant types unconfirmed.');
  if (!description) warnings.push('Source has no description.');
  if (grant_status === 'forecasted') {
    dv = first(syn.estApplicationResponseDateStr, syn.estApplicationResponseDate, dv);
    deadline_text = 'Estimated forecast deadline. ' + deadline_text;
    warnings.push('Forecast dates and requirements may change.');
  }
  const deadline = parseDate(dv);
  if (!deadline) {
    warnings.push('Application deadline unknown.');
    if (dv) deadline_text += ' ' + plain(dv);
  }
  let award_min = parseAmount(first(syn.awardFloor, syn.awardFloorFormatted)),
    award_max = parseAmount(first(syn.awardCeiling, syn.awardCeilingFormatted));
  if (award_min !== null && award_max !== null && award_min > award_max) {
    award_min = award_max = null;
    warnings.push('Contradictory award range; confirm amounts.');
  }
  if (award_min === 0 || award_max === 0)
    warnings.push('Zero award boundary; confirm whether this means unspecified funding.');
  const agency = syn.agencyDetails || raw.agencyDetails || {};
  const requirements = (raw.synopsisAttachmentFolders || [])
    .flatMap((f) =>
      (f.synopsisAttachments || [])
        .map((a) => plain(first(a.fileDescription, a.fileName)))
        .filter(Boolean),
    )
    .map((a) => 'Announcement attachment (review requirements): ' + a);
  if (!requirements.length)
    warnings.push('Application materials not extracted; review the announcement.');
  const cost =
    typeof syn.costSharing === 'boolean'
      ? syn.costSharing
      : ({ true: true, false: false, yes: true, no: false }[
          String(syn.costSharing).toLowerCase()
        ] ?? null);
  return grantSchema.parse({
    source: 'Grants.gov',
    source_id: id,
    source_url: `https://www.grants.gov/search-results-detail/${id}`,
    grant_title,
    description,
    eligibility_text,
    applicant_types,
    funder_name:
      plain(first(agency.agencyName, search.agency, search.agencyName, raw.agencyName)) ||
      'Unknown',
    application_url: link(first(raw.assistURL, raw.applicationUrl)),
    categories: descriptions(syn.fundingActivityCategories),
    program_areas: [
      ...new Set([...descriptions(raw.alns || raw.cfdas), ...descriptions(syn.fundingInstruments)]),
    ],
    award_min,
    award_max,
    deadline,
    deadline_text,
    grant_status,
    open_date: parseDate(first(syn.postingDateStr, syn.postingDate, search.openDate, raw.openDate)),
    matching_funds_required: cost,
    application_requirements: requirements,
    contact_information: [
      ...new Set(
        ['agencyContactName', 'agencyContactEmail', 'agencyContactPhone', 'agencyContactDesc']
          .map((k) => plain(syn[k]))
          .filter(Boolean),
      ),
    ].join('; '),
    raw_text: [grant_title, description, eligibility_text, deadline_text].join('\n'),
    warnings,
  });
}
export async function* federal(
  keywords,
  maxRecords,
  { post = api, stats = { found: 0, rejected: 0, truncated: false }, errors = [] } = {},
) {
  const seen = new Set(),
    pages = new Set();
  let searches = keywords.map((keyword) => ({ keyword, offset: 0 })),
    count = 0;
  while (searches.length && seen.size < maxRecords) {
    const next = [];
    for (const search of searches) {
      if (seen.size >= maxRecords) {
        next.push(search);
        continue;
      }
      if (++count > Math.min(1000, maxRecords * 2 + keywords.length)) {
        stats.truncated = true;
        errors.push('Search page safety limit reached.');
        return;
      }
      const rows = Math.min(
        25,
        Math.max(1, Math.floor(maxRecords / Math.max(1, keywords.length))),
        maxRecords - seen.size,
      );
      try {
        const data = await post('search2', {
          keyword: search.keyword,
          rows,
          oppStatuses: 'forecasted|posted',
          startRecordNum: search.offset,
          sortBy: 'openDate|desc',
        });
        if (!Array.isArray(data.oppHits)) throw new Error('Missing opportunity hit list.');
        const hits = data.oppHits;
        stats.found += hits.length;
        const sig = search.keyword + '|' + hits.map((h) => h.id).join(',');
        if (hits.length && pages.has(sig))
          throw new Error('Repeated API page; pagination stopped.');
        pages.add(sig);
        if (hits.length && search.offset + hits.length < Number(data.hitCount ?? hits.length))
          next.push({ ...search, offset: search.offset + hits.length });
        for (const hit of hits) {
          const id = String(hit.id ?? '');
          if (!/^\d+$/.test(id)) {
            stats.rejected++;
            errors.push('Skipped malformed opportunity ID.');
            continue;
          }
          if (seen.has(id)) continue;
          if (seen.size >= maxRecords) {
            stats.truncated = true;
            break;
          }
          seen.add(id);
          try {
            const raw = await post('fetchOpportunity', { opportunityId: Number(id) });
            if (String(raw.id) !== id) throw new Error('Detail ID mismatch.');
            yield normalizeFederal({ ...raw, _search: hit });
          } catch (e) {
            stats.rejected++;
            errors.push(`Opportunity ${id}: ${e.message}`);
          }
        }
      } catch (e) {
        errors.push(`Search ${search.keyword}: ${e.message}`);
      }
    }
    searches = next;
  }
  if (searches.length || stats.truncated) {
    stats.truncated = true;
    errors.push(`Reached the ${maxRecords}-opportunity cap; results are a bounded subset.`);
  }
}
export async function approvedPage(source, { fetch = request, wait = delay } = {}) {
  if (!source.enabled || !source.terms_reviewed)
    throw new Error('Source needs enabled status and terms review.');
  const url = new URL(source.url),
    robotsUrl = new URL('/robots.txt', url).href;
  const robotsText = (await fetch(robotsUrl, { limit: 500000 })).text;
  if (!/user-agent\s*:/i.test(robotsText))
    throw new Error('Missing robots directives; source skipped.');
  const robots = robotsParser(robotsUrl, robotsText);
  if (robots.isAllowed(url.href, 'GrantIQ') !== true)
    throw new Error('Robots rules do not allow this page.');
  const crawl = Number(robots.getCrawlDelay('GrantIQ') || 1);
  if (crawl > 60) throw new Error('Crawl delay exceeds this worker budget.');
  await wait(Math.max(1000, crawl * 1000));
  const response = await fetch(url.href);
  if (!String(response.headers['content-type'] || '').includes('text/html'))
    throw new Error('Approved source must return HTML.');
  const $ = cheerio.load(response.text);
  if (
    $('input[type=password]').length ||
    /cf-chl-|g-recaptcha|h-captcha|verify you are human/i.test(response.text)
  )
    throw new Error('Login or access challenge; source skipped.');
  $('script,style,nav,footer').remove();
  const rules = source.selectors || {};
  const text = (key, fallback = '') =>
    plain(
      $(rules[key] || fallback)
        .first()
        .text(),
    );
  const vals = (key) =>
    rules[key]
      ? $(rules[key])
          .map((_, e) => plain($(e).text()))
          .get()
          .filter(Boolean)
      : [];
  const application = rules.application_url ? $(rules.application_url).first().attr('href') : null;
  const grant_status = text('status') || 'unknown',
    geography_scope = text('geography_scope') || 'unknown';
  return grantSchema.parse({
    source: 'Approved page',
    source_id: String(source.id),
    source_url: url.href,
    grant_title: text('title', 'h1') || text('title', 'title'),
    description: text('description', 'main') || plain($('body').text()),
    funder_name: source.name,
    eligibility_text: text('eligibility'),
    deadline: parseDate(text('deadline')),
    deadline_text: text('deadline'),
    award_min: parseAmount(text('award_min')),
    award_max: parseAmount(text('award_max')),
    application_url: application ? link(new URL(application, url).href) : null,
    applicant_types: vals('applicant_types'),
    geographic_restrictions: vals('geographic_restrictions'),
    populations_served: vals('populations_served'),
    categories: vals('categories'),
    program_areas: vals('program_areas'),
    grant_status: ['posted', 'forecasted', 'closed', 'archived', 'unknown'].includes(grant_status)
      ? grant_status
      : 'unknown',
    geography_scope: ['local', 'state', 'regional', 'national', 'unknown'].includes(geography_scope)
      ? geography_scope
      : 'unknown',
    raw_text: plain($('body').text()),
    warnings: ['Approved single-page extraction: verify missing fields with official evidence.'],
  });
}
