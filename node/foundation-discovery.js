import { createHash } from 'node:crypto';
import { request, delay } from './network.js';
import { httpUrl } from './validation.js';
import { funderKey } from './matching.js';
import { now } from './store.js';

// Rotate bounded research queries. No private exclusions, staff notes or donor
// amounts are sent to either provider. Headquarters location is not eligibility.
const themes = [
  'vision care',
  'school health',
  'healthcare access',
  'older adults',
  'education equity',
  'cataract surgery',
  'mobile clinics',
  'general operating support',
];
const locations = ['Jacksonville', 'Northeast Florida', 'Florida', 'Southeast', 'United States'];
export function foundationQueries(cursor = 0) {
  return Array.from({ length: 3 }, (_, i) => {
    const n = cursor + i;
    return `${themes[n % themes.length]} foundation grants ${locations[Math.floor(n / themes.length) % locations.length]} application guidelines`;
  });
}

export async function* foundationLeads(
  config,
  cursor,
  { errors, fetch = request, pause = delay } = {},
) {
  if (config.foundationDiscovery) {
    // The API searches organization names/cities, not grant descriptions.
    // Rotate national and Florida name searches; these are research leads only.
    const terms = ['foundation', 'eye', 'vision', 'health', 'community'];
    const params = new URLSearchParams({
      q: terms[cursor % terms.length],
      page: String(Math.floor(cursor / 5) % 4),
      'c_code[id]': '3',
    });
    if (Math.floor(cursor / 20) % 2 === 0) params.set('state[id]', 'FL');
    try {
      const data = JSON.parse(
        (await fetch(`https://projects.propublica.org/nonprofits/api/v2/search.json?${params}`))
          .text,
      );
      if (!Array.isArray(data.organizations))
        throw new Error('Malformed nonprofit directory response.');
      for (const org of data.organizations.slice(0, 25)) {
        if (!/^\d{1,9}$/.test(String(org.ein))) continue;
        if (
          !/foundation/i.test(org.name || '') &&
          !/^T(?:20|21|22|30|31)/i.test(org.ntee_code || '')
        )
          continue;
        yield {
          provider: 'ProPublica Nonprofit Explorer',
          title: String(org.name || 'Unnamed organization'),
          url: `https://projects.propublica.org/nonprofits/organizations/${org.ein}`,
          summary: `Organization located in ${org.city || 'unknown city'}, ${org.state || 'unknown state'}. Historical IRS records; grantmaking, Florida eligibility and open applications are not verified.`,
          ein: String(org.ein),
          query: params.get('q'),
          kind: 'Historical filing prospect',
        };
      }
    } catch (e) {
      errors.push(`Foundation directory: ${e.message}`);
    }
  }
  if (!config.webSearchKey) return;
  for (const q of foundationQueries(cursor)) {
    try {
      const params = new URLSearchParams({ q, count: '10', country: 'US', search_lang: 'en' });
      const data = JSON.parse(
        (
          await fetch(`https://api.search.brave.com/res/v1/web/search?${params}`, {
            headers: { 'X-Subscription-Token': config.webSearchKey },
          })
        ).text,
      );
      if (!data.web || !Array.isArray(data.web.results))
        throw new Error('Malformed web-search response.');
      for (const hit of data.web.results) {
        if (!httpUrl.safeParse(hit.url).success) continue;
        yield {
          provider: 'Brave Search',
          title: String(hit.title || hit.url),
          url: hit.url,
          summary: String(hit.description || ''),
          query: q,
          kind: 'Unverified web lead',
        };
      }
    } catch (e) {
      errors.push(`Web discovery: ${e.message}`);
    }
    await pause(1100);
  }
}

export function saveLead(s, lead) {
  s.discoveryLeads ||= [];
  const name = funderKey(lead.title);
  // A title match suppresses known funders; staff must verify aliases on web leads.
  if (s.profile.excluded_funders.some((f) => name === funderKey(f))) return false;
  const url = new URL(lead.url);
  url.hash = '';
  for (const key of [...url.searchParams.keys()])
    if (key.startsWith('utm_')) url.searchParams.delete(key);
  const id = createHash('sha256').update(url.href).digest('hex');
  const existing = s.discoveryLeads.find((x) => x.id === id);
  if (existing) {
    existing.last_seen = now();
    return false;
  }
  // Bound workspace growth without silently deleting staff-reviewed leads.
  if (s.discoveryLeads.length >= 5000) return false;
  s.discoveryLeads.push({
    ...lead,
    url: url.href,
    id,
    first_seen: now(),
    last_seen: now(),
    disposition: 'Verify',
    notes: '',
  });
  return true;
}
