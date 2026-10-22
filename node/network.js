import dns from 'node:dns/promises';
import http from 'node:http';
import https from 'node:https';
import ipaddr from 'ipaddr.js';
import { httpUrl } from './validation.js';
export function isPublic(address) {
  try {
    const ip = ipaddr.process(address);
    return ip.range() === 'unicast';
  } catch {
    return false;
  }
}
export async function publicAddress(url, lookup = dns.lookup) {
  const u = new URL(httpUrl.parse(url));
  if (u.port && !['80', '443'].includes(u.port))
    throw new Error('Only standard public web ports are permitted.');
  const host = u.hostname.replace(/^\[|\]$/g, '');
  const addresses = await lookup(host, { all: true });
  if (!addresses.length || addresses.some((a) => !isPublic(a.address)))
    throw new Error('Source must resolve only to public addresses.');
  return { url: u, address: addresses[0] };
}
// Resolve, validate and pin the IP for this connection. Redirects are never followed.
export async function request(
  url,
  { method = 'GET', body = null, limit = 2_000_000, timeout = 25000 } = {},
) {
  const { url: u, address } = await publicAddress(url);
  return new Promise((resolve, reject) => {
    const transport = u.protocol === 'https:' ? https : http;
    const req = transport.request(
      u,
      {
        method,
        headers: {
          'User-Agent': 'GrantIQ/0.2 (+grant research; contact site administrator)',
          Accept: 'application/json,text/html,text/plain',
          'Accept-Encoding': 'identity',
          ...(body ? { 'Content-Type': 'application/json' } : {}),
        },
        lookup: (_host, options, cb) =>
          options.all ? cb(null, [address]) : cb(null, address.address, address.family),
      },
      (res) => {
        if (res.statusCode < 200 || res.statusCode >= 300) {
          res.resume();
          reject(
            new Error(
              `Source returned HTTP ${res.statusCode}; redirects/access challenges are not followed.`,
            ),
          );
          return;
        }
        const chunks = [];
        let size = 0;
        res.on('data', (chunk) => {
          size += chunk.length;
          if (size > limit) {
            res.destroy(new Error('Source exceeds response-size limit.'));
            return;
          }
          chunks.push(chunk);
        });
        res.on('error', reject);
        res.on('end', () =>
          resolve({ text: Buffer.concat(chunks).toString('utf8'), headers: res.headers }),
        );
      },
    );
    const timer = setTimeout(() => req.destroy(new Error('Source request timed out.')), timeout);
    req.on('close', () => clearTimeout(timer));
    req.on('error', reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}
export const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
export async function api(endpoint, payload) {
  let error;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      await delay(350);
      const response = await request(`https://api.grants.gov/v1/api/${endpoint}`, {
        method: 'POST',
        body: payload,
      });
      const raw = JSON.parse(response.text);
      if (!raw.data || typeof raw.data !== 'object' || ![0, '0', undefined].includes(raw.errorcode))
        throw new Error('Malformed Grants.gov API response.');
      return raw.data;
    } catch (e) {
      error = e;
      if (attempt < 2) await delay(500 * 2 ** attempt);
    }
  }
  throw error;
}
