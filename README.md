# GrantIQ

Grant discovery, explainable matching, and staff pipeline management. The primary web application now runs **natively on Node.js**, with Express and PostgreSQL for SiteGround hosting. It does not launch Python or require a paid AI service.

## Run on a computer

Install Node.js **22.13+ (22.x) or 24.x**, including npm. From this project folder:

```sh
npm ci
npm run build
npm start
```

Open **http://127.0.0.1:3000**. Keep the terminal open. Local data uses `data/node/grantiq.sqlite`, separate from the Python database. A new public checkout starts with safe configuration and an empty grant collection.

Optional local configuration: copy `.env.node.example` to `.env.node`. For Windows everyday use, double-click `Start-GrantIQ-Node.cmd` after installation. The old Python launcher is retained for the legacy version.

For semantic matching rather than the clearly disclosed keyword fallback:

```sh
npm run model:download
```

Set `GRANTIQ_SEMANTIC_MODE=local` in `.env.node`, restart, and run `npm run rescore`. This uses Transformers.js MiniLM locally on CPU. Test model memory and native-library support on the destination host. The cached ONNX weights are separate from Python's weights.

## SiteGround

See **[SITEGROUND.md](SITEGROUND.md)** for the exact build/start settings, PostgreSQL setup, environment variables, data migration, authentication, model choices, and deployment checks. Use the Express/custom Node preset, `npm run build`, and `npm start`. Production requires managed PostgreSQL, a shared staff password, a random session secret, and allowed hostnames.

The code is prepared for SiteGround; account-level deployment and persistence/restart behavior must still be verified there. No SiteGround purchase or live deployment is performed by installing this repository.

## Workflows

- Grants.gov discovery with bounded, rotating keyword searches and full detail retrieval.
- Persistent 3/6/12/24-hour scheduling, heartbeat, failure/partial results and overlap protection.
- Organization profile, seven scoring weights, eligibility gates, and separate completeness confidence.
- Eight pipeline stages with notes, assignee, requested amount, dates and final result.
- Staff funder exclusions and research dispositions, kept separate from legal eligibility.
- Approved single-page public sources with terms review, robots checks, IP validation, pinned DNS, and response limits.
- Evidence-backed fact verification, expiry, source-change invalidation and withdrawal history.
- Filtered discovery and spreadsheet-safe CSV export.
- Shared staff sign-in, signed expiring sessions, CSRF protection and login throttling.

Matching scores guide investigation, not award probabilities. Missing facts remain unknown. Without the semantic model, the mission component earns only its 35% keyword share. Applications are not submitted automatically.

## Moving the Python workspace

Create a consistent backup of the Python database, then import into an unused Node database:

```sh
npm run import:python -- /path/to/grantiq-snapshot.db
```

The source is opened read-only. Profile, grants, pipeline, approved sources, research decisions, review history, search cursor and recent runs are retained. The imported schedule is paused. Historical verified corrections require renewed review because their hash encoding differs. Follow SITEGROUND.md before transferring private data or enabling searches.

The legacy Python implementation remains under `grantiq/`; its setup is documented in **[README-PYTHON.md](README-PYTHON.md)**. Do not run both schedulers against the same workspace. New Node work uses its own store; changes do not synchronize back to Python.

## Structure

```text
node/
  server.js             HTTP lifecycle and scheduler startup
  app.js                Browser routes, forms, CSV, access controls
  views.js              Escaped server-rendered HTML
  public/               Grayscale responsive CSS and status polling
  config.js             Environment validation; production fails closed
  store.js              Atomic PostgreSQL / local SQLite workspace store
  service.js            Discovery coordinator, leases, filters, staff updates
  matching.js           Eligibility, seven score components, verification
  embeddings.js         Optional native Node MiniLM inference
  network.js            Bounded public requests with DNS pinning
  sources.js            Grants.gov and approved-page normalization
  validation.js         Shared Zod input contracts
  scripts/              Build check, refresh, rescore, read-only SQLite import
  tests/                Workflow, security, source, migration, parity tests
config/examples/        Safe public research templates
config/organization.yaml Initial organization profile
package-lock.json       Locked Node dependencies
SITEGROUND.md           Deployment and handoff guide
```

## Verification

```sh
npm test
npm run build
npm audit --omit=dev
```

Thirty synthetic fixtures compare Node eligibility and component scores with the Python reference implementation. Other tests cover HTTP workflows, security, failed sources, staff-data preservation, import and locks. Tests do not require a model download or live grants API. The PostgreSQL integration case runs when `GRANTIQ_TEST_POSTGRES_URL` points to a **disposable test database**; it resets that test workspace. GitHub Actions supplies PostgreSQL for this case.

For an optional real-model smoke test: `npm run model:download`. For a manual real search: `npm run refresh`. Partial/failed CLI searches exit nonzero and retain successful records.

Private configuration, `.env.node`, data, research PDFs and internal meeting notes remain excluded from Git and deployment packages. Public clones show a public project overview at `/sprint-review`; private PDF routes are not part of this Node version.
