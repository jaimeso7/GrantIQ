import { esc, form } from './html.js';
import { icon } from './icons.js';

const navigation = [
  ['/', 'Discover grants', 'grid'],
  ['/pipeline', 'My pipeline', 'bookmark'],
  ['/research', 'Team research', 'search'],
  ['/sources', 'Data sources', 'database'],
  ['/settings', 'Organization profile', 'settings'],
];

/** Shared original-style shell. Profile names are supplied only after authentication. */
export function layout(
  title,
  body,
  { token = '', notice = '', auth = false, pathname = '', organization = 'Your organization' } = {},
) {
  const activePath = pathname.startsWith('/grants/') ? '/' : pathname;
  const nav = navigation
    .map(([href, text, glyph]) => {
      const active = href === '/' ? activePath === '/' : activePath.startsWith(href);
      return `<a href="${href}" class="nav-item ${active ? 'active' : ''}" ${active ? 'aria-current="page"' : ''}>${icon(glyph)}<span>${text}</span></a>`;
    })
    .join('');
  // Discovery and pipeline supply their original headings inside the page.
  const heading = ['/', '/pipeline'].includes(pathname)
    ? ''
    : `<section class="page-heading"><div><p class="eyebrow">YOUR GRANTIQ WORKSPACE</p><h1>${esc(title)}</h1></div></section>`;
  return /* HTML */ `<!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta name="theme-color" content="#ffffff" />
        <title>${esc(title)} · GrantIQ</title>
        <link rel="stylesheet" href="/static/original.css" />
        <link rel="stylesheet" href="/static/node.css" />
        <script src="/static/node.js" defer></script>
      </head>
      <body>
        <a class="skip-link" href="#main">Skip to main content</a>
        <aside class="sidebar">
          <a class="brand" href="/" aria-label="GrantIQ home"
            ><span class="brand-mark">${icon('spark')}</span
            ><span
              >Grant<span class="brand-light">IQ</span><span class="brand-dot">.</span></span
            ></a
          >
          <div class="workspace">
            <span class="workspace-avatar">${icon('building')}</span>
            <div><small>YOUR ORGANIZATION</small><strong>${esc(organization)}</strong></div>
          </div>
          <a class="nav-item" href="/sprint-review">${icon('grid')}<span>Sprint review</span></a>
          <p class="nav-label">WORKSPACE</p>
          <nav aria-label="Main navigation">${nav}</nav>
          <div class="sidebar-bottom">
            <div class="mission-note">
              <span class="tiny-spark">${icon('spark')}</span>
              <p>A little clarity.<br /><strong>A bigger impact.</strong></p>
              <span>Grant discovery built around your mission.</span>
            </div>
            <div class="sidebar-footer">More opportunity. More impact.</div>
            ${auth ? form('/logout', token, '', 'Sign out') : ''}
          </div>
        </aside>
        <div class="main-shell">
          <header class="topbar">
            <span class="breadcrumb">Workspace <span>/</span> ${esc(title)}</span>
            <div class="topbar-right">
              <span class="topbar-tag">MISSION-DRIVEN FUNDING</span
              ><span class="user-avatar" aria-label="Organization"
                >${esc(organization.slice(0, 1).toUpperCase())}</span
              >
            </div>
          </header>
          <main id="main" class="main-content">
            ${notice
              ? `<div class="notice" role="status">${icon('info')}<span>${esc(notice)}</span></div>`
              : ''}
            ${heading}${body}
            <footer class="main-footer">
              <span>GrantIQ / More opportunity. More impact.</span
              ><span>Verify eligibility and deadlines with the official funder.</span>
            </footer>
          </main>
        </div>
      </body>
    </html>`;
}
