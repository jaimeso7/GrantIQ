# Foundation discovery and grant watch

The Node application now uses the `grant-watch-1` policy. Open **Foundation watch**
in the sidebar (`/watch`). No LLM is required for this implementation. MiniLM
continues to supply local semantic similarity; deterministic rules enforce
eligibility and explain the score.

## What runs automatically

The existing recurring worker runs the following sources while the server is
awake and scheduling is enabled:

1. Public foundation prospecting through ProPublica Nonprofit Explorer: one
   bounded directory request per run, rotating name queries, pages and Florida /
   national scope. This API searches organization names and cities, not grant
   descriptions. Candidates are filtered for foundation names or grantmaking
   NTEE codes. They are **unverified research leads**, not verified grantmakers
   or open grants. Tax filings are historical records.
2. Optional Brave Search discovery: three rotating foundation-oriented searches
   per run, up to ten results each. Queries span vision, school health, healthcare
   access, older adults, education, surgical care, mobile clinics and operations,
   across local, Florida, regional and national geography. This is bounded search,
   not complete coverage of the web.
3. Grants.gov opportunity collection and staff-approved official funding pages.
   Approved pages are rechecked subject to terms review and robots restrictions.

Search results enter the foundation inbox with attribution, source URL, first-seen
and last-seen times. Matching URLs are deduplicated; tracking parameters and URL
fragments do not create new leads. Staff decisions survive repeat searches.
Exact normalized funder-name exclusions apply to directory titles; staff must
check aliases and funder identity on web results before pursuing them. The
existing opportunity-level exclusion/alias system remains in place.

The research inbox retains up to 5,000 leads and displays the latest 100 active
leads. It does not crawl arbitrary search results automatically or bypass logins.
Choose **Create opportunity to verify** after finding an official program. Enter
its actual funder/program and official URL, then use the evidence review form.
This creates an unknown-status record; it does not infer an award or opening from
a snippet. Add its official page under Data sources for continued monitoring.

## Setup and cost controls

Public prospecting defaults on; `GRANTIQ_FOUNDATION_DISCOVERY=false` disables it.
No paid account is created by this code.

For broader web discovery, obtain an authorized Brave Search API subscription
that permits the intended storage/use of results. Set `GRANTIQ_BRAVE_API_KEY` in
Railway service variables or the ignored local `.env.node`, then restart/redeploy.
Never put the key in Git, a browser form or staff notes. Without this key, web
search is inactive; the Sources page shows the last run's provider configuration.
At a three-hour schedule, three queries/run means up to 24 scheduled web queries
per day, plus manual runs. Provider billing is separate from Railway hosting;
check the selected subscription and dashboard limits before enabling it.

Candid is **not connected**. Confirm whether the organization's subscription
includes API access, which API product, permitted storage/use, and credentials.
Foundation Directory/browser access must not be treated as API permission.
Candid's historical Grants API and its Open grant opportunities API serve
different purposes. Historical recipient giving supports prospect research;
current guidelines establish application eligibility and timing.

## Scoring and application planning

| Component                           | Points |
| ----------------------------------- | -----: |
| Mission / program alignment         |     25 |
| Geographic eligibility              |     20 |
| Populations                         |     15 |
| Funding purpose / eligible expenses |     15 |
| Application accessibility           |     10 |
| Potential funding value             |     10 |
| Timing / feasibility                |      5 |

90+ is Exceptional Fit, 75–89 Strong Fit, 60–74 Moderate Fit, and below 60
Lower Priority. Explicit eligibility failures override the score. Unresolved
eligibility is provisional. Unknown award values, eligible purposes and
application accessibility earn no points in their respective categories. Timing
points require posted status. Semantic fallback remains disclosed and capped.
These are explainable heuristic rankings, not predictions of award probability.
Funding-purpose overlap cannot establish that a particular expense is allowed;
staff must verify exclusions and eligible expenses in the official guidelines.

Imported legacy profile weights remain stored for compatibility, but are not the
active scoring policy. Opening a grant/dashboard/watch page migrates stale
assessments to the current version; the first load of a large workspace can take
longer. `npm run rescore` is also available. Staff pipeline and review history are
preserved. The retained Python application continues to use its legacy scorer.

Grant detail pages show LOI/invitation routes, relationship/match/sponsor barriers
and known stages. Unknown effort is explicitly labeled. Staff can enter
preparation hours and a proposed project angle in the pipeline; these are planning
estimates, not requirements invented by the application.

## Watch report and limits

The watch report separates actionable strong verified opportunities, confirmed
future openings, invitation-only contacts to investigate, material source updates,
and verified deadlines in the next 60 days. A contact is not a confirmed invitation.
Polling timestamps and changed search snippets do not generate material updates.
First seen does not mean newly announced. Updates are shown in the application;
this change does not send email or push notifications. Empty report sections mean
no stored opportunities meet those criteria, not that no such grants exist.

## Code path

`discovery.js` → `foundation-discovery.js` → private workspace lead inbox →
staff official-source verification → `service.js` → `grant-watch.js` →
`watch-report.js` / `ui/watch.js` → staff application pipeline.

Provider requests use the existing public-address validation, pinned DNS, timeout,
response-size limits and redirect rejection in `network.js`. An authorized search
token is sent only to the fixed Brave API endpoint. Private notes and donor amounts
are not included in search queries. No private source document is committed.

## Primary references

- [ProPublica API methods and source attribution](https://projects.propublica.org/nonprofits/api/)
- [Brave Search API request and authentication documentation](https://api-dashboard.search.brave.com/app/documentation/web-search/get-started)
- [Candid Grants API: historical grants, funders and IRS data](https://developer.candid.org/reference/get-started-with-grants-api)
- [Candid API products, including Open grant opportunities](https://candid.org/data/explore-apis/)
