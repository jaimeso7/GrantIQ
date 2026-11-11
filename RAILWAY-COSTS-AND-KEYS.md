# GrantIQ: coordinator briefing — Railway, credentials and costs

Checked November 10, 2026. Prices in USD before tax. Estimates are planning
allowances, not measured GrantIQ bills or guaranteed spending caps.

## Hosting decision

Railway is the selected platform. Use the `codex/railway` branch, the checked-in
`railway.json` and `Dockerfile.railway`, plus a PostgreSQL service.
The [static-hosting guide](https://railway.com/guides/static-hosting) is useful
for simple frontend sites, but GrantIQ also runs authenticated server routes,
database writes, semantic matching and scheduled searches. It needs the full
Node service; uploading HTML alone will not run these features.

## What credentials do we actually need?

| Credential or connection                 | Required?                                                | Where it comes from / cost                                                                                                                                                           |
| ---------------------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `DATABASE_URL` or `GRANTIQ_DATABASE_URL` | Required for hosting                                     | Reference `${{Postgres.DATABASE_URL}}` from Railway's PostgreSQL service. Includes database credentials; resource usage is billed by Railway, not a separate API license.            |
| `GRANTIQ_ADMIN_PASSWORD`                 | Required                                                 | Staff password chosen privately; no separate fee. Current app uses a shared staff login, not named roles.                                                                            |
| `GRANTIQ_SECRET_KEY`                     | Required                                                 | Generate a random secret of at least 32 characters; no separate fee. Keep stable across redeploys.                                                                                   |
| GitHub connection                        | Required for automatic GitHub deployments                | Authorize Railway's GitHub integration for this repository. No GitHub personal token needs to be stored in GrantIQ.                                                                  |
| Railway API token                        | Not required for dashboard/GitHub deployment             | Only needed if a separate CLI/API automation is added.                                                                                                                               |
| `GRANTIQ_BRAVE_API_KEY`                  | Required only for broader web discovery                  | Obtain from the organization's Brave Search API account. Adapter is implemented; inactive without the key.                                                                           |
| Candid API credential                    | Not required for the current application                 | Integration is pending. Confirm VIP's exact API product and contract first; a browser subscription is not evidence of API access. No Candid environment variable is implemented yet. |
| Grants.gov key                           | Not required by the current public search/detail adapter | No API fee configured. Public endpoint availability and limits still apply.                                                                                                          |
| ProPublica key                           | Not required by the current public directory adapter     | No API fee configured; identifies historical filing prospects, not confirmed open grants.                                                                                            |
| OpenAI / Anthropic / other LLM key       | Not required                                             | Current matching uses rules and local MiniLM. No per-token LLM bill; model RAM/CPU contributes to hosting usage.                                                                     |
| Email service key                        | Not required                                             | Automated email alerts are not implemented; reports are viewed in the app.                                                                                                           |

Keep secrets in Railway service Variables and an organization-controlled password
manager. Do not include actual values in GitHub, slides, screenshots or meeting notes.
Other required setup includes a generated Railway domain (or an exact allowed-host
list). Railway supplies the port. Follow RAILWAY.md for runtime configuration.

## Published prices and likely budget

Railway lists Hobby at a **$5 monthly minimum** including $5 of resource usage,
and Pro at a **$20 monthly minimum** including $20 of resource usage. Hobby is
positioned for a single developer; Pro includes workspace seats for a team.
For VIP ownership and staff/developer handoff, budget around Pro. These minimums
are not added again to the same included usage: $30 eligible usage on Pro is
approximately $30, not $50. Extra services and usage can increase the bill.
[Railway pricing](https://railway.com/pricing)

Published resource rates are $0.00000386/GB-second RAM,
$0.00000772/vCPU-second CPU, $0.00000006/GB-second volume storage and
$0.05/GB service egress. For a 30-day month those are approximately
$10/GB RAM, $20/vCPU and $0.16/GB volume storage. Usage is across the app and
database; setting a resource limit does not mean that capacity is constantly used.
[Railway pricing](https://railway.com/pricing)

Illustrative calculations, not observed GrantIQ consumption:

| Combined app + database average usage         | Approximate resource bill | Pro minimum applied |
| --------------------------------------------- | ------------------------: | ------------------: |
| 1 GB RAM, 0.1 vCPU, 5 GB volume, 10 GB egress |              $13.28/month |           $20/month |
| 3 GB RAM, 0.3 vCPU, 5 GB volume, 10 GB egress |              $37.28/month |        $37.28/month |

Allow **$20–$40/month for a small Railway pilot**, then revise after measuring
full searches and rescoring. Backups, storage growth, staging, heavier workloads
and taxes are outside these illustrative calculations. Keep the recurring-search
service awake; do not assume static-site or sleeping-service costs apply.

Brave currently lists **Search at $5/1,000 requests**, with $5 monthly credits.
The current implementation makes three requests per search run. Every three
hours means 720 requests per 30-day month: **$3.60 at list rate before credits**.
Manual searches and other usage add requests. Budget **$0–$5/month initially**,
subject to the account's credits and storage rights. GrantIQ saves results, so
confirm that the selected plan permits storage; standard headline pricing alone
does not establish that permission. [Brave pricing and storage FAQ](https://brave.com/search/api/)

Candid's public catalog lists the historical **Grants API starting at $6,000**
and **Open grant opportunities API as quote-based**. The displayed starting price
does not specify a billing term on that page; request a written quote and confirm
whether VIP already has access, nonprofit pricing, quotas and storage rights.
Do not include this in the small hosting allowance or purchase it yet.
[Candid API catalog](https://candid.org/data/explore-apis/)

Suggested initial planning envelope: **$25–$45/month ($300–$540/year)** for
Railway plus a small search allowance, excluding Candid, tax, a separately
purchased domain, extra backup/storage charges and developer maintenance time.
This is a proposal to discuss, not a purchase or hard cap. Existing VIP domain
use can avoid buying another domain. No paid LLM is needed for the current build.

## Decisions for the meeting

1. Put Railway billing, GitHub ownership/access and API accounts under VIP control;
   assign a backup administrator and a named technical maintainer.
2. Approve a pilot budget and usage alerts. A hard spending limit can stop the app
   and scheduled searches, so agree on the continuity tradeoff.
3. Confirm whether VIP's Candid subscription includes an API; request the product
   name, contract period, quote, quotas and permitted storage/use. Never share keys
   in this document.
4. Authorize Brave only with appropriate storage rights, then configure its key.
5. Validate a Railway deploy, restore a backup, verify a scheduled search while the
   developer's laptop is off, and measure peak memory before production handoff.

Suggested talking point: “Railway runs the application and database. Web search is
a separate optional API expense. We can start without a paid LLM, and we should
confirm Candid's API entitlement before committing to a potentially larger license.”

Provider sources were checked on the date above; checkout and VIP's actual
agreements determine final charges. No provider account or subscription was
created or changed as part of preparing this briefing.
