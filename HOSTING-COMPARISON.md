# GrantIQ hosting decision for VIP

Prepared October 25, 2026. USD estimates before tax. Recommendation: Railway Pro for a small shared team deployment, with an initial **$20–$40/month planning allowance ($240–$480/year)** and measured review after the first full month. This is a budget estimate, not a provider quote or a spending cap. If VIP already pays for an eligible SiteGround plan with spare resources, test that first: incremental hosting cost may be zero.

## Compatibility

Railway fits the existing Node.js 22/Express app, PostgreSQL database and CPU-based MiniLM matching model. No further framework rewrite is required. The new Railway configuration selects the Node container instead of the legacy Python Dockerfile, bundles the model and keeps the service awake for scheduled searches. Staff use an HTTPS URL from any computer; nobody installs Node on their own computer.

SiteGround also supports this architecture on GrowBig, GoGeek and Cloud. StartUp does not include Node.js Projects. Native model resource use still needs verification on either host. SiteGround includes PostgreSQL and GitHub deployment in the eligible plans. [SiteGround Node.js announcement](https://www.siteground.com/blog/hosting-node-js-projects-with-siteground)

## Resource sufficiency

Railway paid-plan capacity is ample for the current small, single-organization prototype. The local Node database file is approximately **14 MB with 543 grants**; PostgreSQL storage, WAL, history and backups will take more. Start with 5 GB of database volume capacity and monitor growth. This is not a guarantee that the database stays that size.

Starting resource limits: app 2 GB RAM / 1 vCPU for semantic matching; database approximately 1 GB RAM. For keyword-only matching, trial a 512 MB–1 GB app limit after measuring it. These are engineering starting points, not load-tested requirements. MiniLM needs no GPU or paid AI API; runtime compute is still billable. Free/trial allowances are unsuitable for promising continuous unattended staff use.

The app stores one workspace document and serializes writes. That is suitable for a small team, but long rescoring can delay other updates. More hosting RAM does not fix that architecture. Large grant collections or many concurrent users will require indexed per-record storage and shorter transactions. Generic source adapters fetch one approved page; hosting does not turn them into a comprehensive grant index.

## Transparent cost model

Railway currently lists RAM at **$10/GB-month**, CPU at **$20/vCPU-month**, volume storage at **$0.15/GB-month**, and outbound transfer at **$0.05/GB**. Actual metered consumption counts across both app and database, plus other services. Build resources are free. [Resource pricing](https://docs.railway.com/pricing/plans)

Hobby has a **$5 monthly minimum**; Pro has a **$20 monthly minimum**, including that amount of usage. Thus $12 usage on Pro costs $20, and $28 usage costs $28, not $48. Pro includes workspace collaboration without additional seat charges. [Billing explanation](https://docs.railway.com/pricing/understanding-your-bill), [workspaces](https://docs.railway.com/projects/workspaces)

Illustrative monthly math, assuming services run all month; these are assumptions, not measured Railway results:

| Scenario | Combined average RAM | Combined average CPU | Stored volume + billable backup data | Egress | Calculated usage | Pro bill |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Light pilot | 0.75 GB = $7.50 | 0.05 vCPU = $1 | 2 GB = $0.30 | 2 GB = $0.10 | $8.90 | $20 |
| Small semantic workload | 1.5 GB = $15 | 0.10 vCPU = $2 | 5 GB = $0.75 | 5 GB = $0.25 | $18 | $20 |
| Higher sustained workload | 3 GB = $30 | 0.25 vCPU = $5 | 10 GB = $1.50 | 10 GB = $0.50 | $37 | $37 |

Allocated limits are not average use. Each additional average 1 GB RAM adds about $10/month in usage; a fully busy average vCPU adds $20/month. Model warm-up, full rescoring, staging environments and database activity can change these estimates. The $20–$40 allowance excludes paid engineering/support labor, tax, a separately purchased domain, external backup storage, optional high availability and future paid grant-data/API subscriptions. A Railway-provided domain avoids buying a custom domain. GrantIQ currently requires no paid AI API or per-staff software subscription.

| Decision | Railway | SiteGround |
| --- | --- | --- |
| Team budget | Pro minimum $20/month; plan $20–$40 for this pilot, measured afterward | GrowBig regular $29.99/month equivalent prepaid 12 months ($359.88), or $34.99 paid monthly |
| Predictability | Variable bill; alerts and hard limits available | More predictable plan bill until an upgrade/add-on is needed |
| Already paying for hosting | Additional app/database usage bill | May fit an existing eligible plan without extra plan cost |
| Updates | GitHub deployments, logs, metrics, rollback tools | GitHub deployments or ZIP uploads; deployment logs |
| Runtime control | Explicit container, separate app/database, adjustable limits | Shared-plan resources; verify Node/native model limits with SiteGround |
| Bundled services | Database consumes billable compute/storage; configure backups | PostgreSQL, SSL and other hosting services bundled in eligible plan |
| Staff experience | Browser only after setup; developer manages infrastructure | Browser only after setup; developer still manages app |

SiteGround prices above use its **regular-rate table updated October 12, 2026**, not introductory offers. Promotional pages can show different prices; use VIP's actual renewal invoice/checkout and prepaid term. Do not assume the headline introductory price lasts. [SiteGround regular rates](https://www.siteground.com/kb/current-rates-shared-hosting-plans), [included plan features](https://www.siteground.com/kb/choose-suitable-hosting-plan)

## Long-term maintenance

Railway makes deployment and troubleshooting relatively straightforward for Jaime/a developer: review changes in GitHub, run CI, deploy, inspect logs and metrics, and roll back application code when necessary. VIP staff can manage grants and notes through the website without learning programming. Neither provider eliminates maintenance: designate a developer for dependency patches, database upgrades, failed searches and restores. Avoid promising that Ashley will troubleshoot hosting herself.

Turn off service sleeping for the embedded recurring-search worker. A sleeping app cannot guarantee scheduled work. Railway's deploy healthcheck is not continuous monitoring. Establish alerts and test scheduled searches while staff computers are off. [Serverless behavior](https://docs.railway.com/deployments/serverless), [healthchecks](https://docs.railway.com/deployments/healthchecks)

## Ownership, backups and security

- VIP should own the Railway workspace, payment method, domain, production database and code organization/repository. Give developers named access; maintain two authorized administrators, enable account MFA and retain recovery credentials under VIP control. Removing a developer should not remove VIP's access to the application.
- Configure database backups explicitly. Railway supports scheduled daily, weekly and monthly volume backups, with incremental backup storage billed for unique data. Test recovery into a separate database and keep encrypted exports outside the hosting account. Do not treat GitHub or an application rollback as a database backup. [Backup documentation](https://docs.railway.com/volumes/backups)
- Use HTTPS, private app-to-database networking, secrets in Railway variables, and no public database endpoint unless temporarily needed for a controlled transfer. Railway private traffic is encrypted with WireGuard. [Private networking](https://docs.railway.com/networking/private-networking)
- The current app uses a **shared staff password**, not individual users, roles, MFA or per-person audit logs. Hosting-account MFA does not add MFA to GrantIQ. Named app accounts, individual access removal and audit history should be a follow-up before broader staff rollout. Private research, funder amounts and backups stay out of public GitHub and container images.
- Railway supplies infrastructure/templates; VIP's technical maintainer still owns backup configuration, restoration drills, database monitoring and upgrades. Higher-availability database arrangements cost additional resources. [Database responsibilities](https://docs.railway.com/platform/use-cases)
- Set budget alerts and decide deliberately whether to apply a hard usage limit: reaching it takes the app and scheduled searches offline. [Cost controls](https://docs.railway.com/pricing/cost-control)

## Meeting decision

Approve a Railway Pro pilot with a $20–$40 monthly planning allowance, VIP ownership and a named technical maintainer, or use existing SiteGround capacity if minimizing incremental cost is the priority. Do not buy a second hosting plan before confirming the existing subscription. Before launch, measure a full search/rescore, test HTTPS login and persistence after redeploy, restore a backup, and verify an unattended scheduled search. Railway deployment and resource measurements remain pending.
