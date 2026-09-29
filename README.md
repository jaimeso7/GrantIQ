# GrantIQ

A free grant discovery and matching MVP for **Vision Is Priceless**. FastAPI, SQLAlchemy, SQLite, Jinja2, and a local SentenceTransformer model. No paid AI service, grant subscription, vector database, or frontend build system is required.

## Start locally

Use **Python 3.12**. Run these commands from this folder:

```bash
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

Then install, prepare the free model, and start:

```bash
python -m pip install -r requirements.txt -c requirements-lock.txt
python -m grantiq.app.services.embeddings --download
python -m uvicorn grantiq.app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Open **http://127.0.0.1:8000**. Review **Organization profile**, click **Refresh grants**, and inspect the score breakdown on an opportunity. Save grants to **My pipeline** and use **Export CSV** to export the current filtered result set, including staff notes.

The first installation downloads Python packages and public model weights. Subsequent scoring uses cached weights on CPU. The database and model cache persist under `data/`. If the model is unavailable, the app still opens and collects grants, but explicitly displays `keyword_fallback`; the semantic share receives no points. Download the model and restart, then refresh or save the profile to rescore.

On Windows, Start-GrantIQ.ps1 uses the project-local .venv. The working project is now located at C:\Users\asoto\Documents\GrantIQ. Cached model weights, the database, and runtime secrets stay in the local data folder and are excluded from Git.

## What is implemented

- Automatic discovery every six hours by default, configurable to 3/6/12/24 hours, with pause/resume, a live status panel, last/next search times, counts, heartbeat health, and failure retries.
- Bright white/charcoal interface with larger supporting text and 16-pixel form inputs.
- Official Grants.gov search and full-opportunity API retrieval, posted and forecasted records, bounded pagination, keyword rotation, retries, rate limiting, and failure logging.
- Editable organization profile, financial preferences, service locations, programs, relationships, seven scoring weights, and readiness thresholds.
- Eligibility checks before scoring, local semantic similarity, deterministic explanations, and a separate data completeness confidence score.
- Dashboard, detailed opportunity pages, filters, CSV export, and all eight requested pipeline statuses with notes, assignee, requested amount, staff deadline, submission date, and final result.
- Persistent SQLAlchemy storage with source identities, canonical records, assessments, staff pipeline entries, and refresh audit records.
- Approved funding-page management in Data sources: add, edit, enable, and disable public single-opportunity pages, with recorded terms review and optional field extraction rules.
- Evidence-backed staff verification of grant facts, automatic rescoring, retained review history, withdrawal, expiry, and invalidation when imported source facts change.
- Unit, database, HTTP-route, source failure, security, and optional real-model integration tests.

**Scope:** This is the working Phase 1 MVP plus the first Phase 2 source-management and research workflows. No foundation or local funding page is enabled by default. Automated 990 ingestion, historic recipient research, comprehensive Florida source coverage, and application drafting are later phases. The app does not submit applications. Past-giving points remain zero without attributed recipient evidence; they are not estimated from a funder's name.

## Data coverage and human review

Live verification on September 14, 2026 collected **100 real federal opportunities**, including 80 with an unexpired or unknown deadline at that time. Collection was deliberately capped and reported as a **partial** refresh, not a complete catalog. This batch produced no confirmed strong matches. Many federal opportunities concern research rather than direct services, and Grants.gov does not consistently expose geographic restrictions, populations, application links, or complete eligibility in structured fields.

GrantIQ does not infer national eligibility merely because a grant is federal. Geography, proposed-project restrictions, invitation conditions, unknown funding, forecast dates, and missing application documents may require staff review. The source text and official link remain available. Scores prioritize investigation; they are not award probabilities or legal determinations. A low completeness confidence or `Needs Review` status must not be treated as confirmed eligibility.

The default organization profile is a paraphrase of the official [About Us](https://visionispriceless.org/about-us/) and [programs](https://visionispriceless.org/our-programs/) pages, checked September 14, 2026. Service locations are Northeast Florida and Jacksonville, Florida. The annual budget, fiscal sponsorship, matching-fund capacity, and funder relationships start unknown. Staff should enter precise confirmed service counties and preferences on the settings page. Lists use **one item per line**; `Jacksonville, Florida` is one location.

The initial profile YAML seeds the database only once. Subsequent edits belong in **Organization profile**. Profile changes recalculate existing assessments in the same database transaction. `last_checked` records retrieval time, not the time a score was recalculated. A cached page retains its original retrieval timestamp.

## Refresh and scheduling

```bash
python -m grantiq.ingestion
python -m grantiq.ingestion --max-records 250
# Equivalent alternate entrypoint:
python scripts/refresh_grants.py --max-records 250
```

The default cap is 100 unique candidates per refresh (`GRANTIQ_MAX_RECORDS`). Searches rotate through configured funding interests and the initial mission-related keywords. A cap or failed source produces a visible `partial`/`failed` status and nonzero CLI exit status. Inspect **Data sources → Refresh activity → collection issues/source results**. An empty search result never deletes existing grants.

Pipeline order:

1. Acquire the instance refresh lock and create an audit record.
2. Search and fetch official source details or approved pages.
3. Strip HTML, validate and normalize records; preserve unknowns.
4. Resolve source identity and cross-source fingerprints.
5. Apply eligibility gates, encode locally, calculate fit and confidence.
6. Commit individual records without changing staff-owned pipeline data.
7. Flag passed deadlines, rescore existing records, and finish the audit.

The web button runs this pipeline in a background worker. Source failures preserve successfully collected records and are visible in the audit. CLI and web refreshes share a file lock. After process interruption, the next refresh marks an abandoned audit run interrupted. The recurring search worker starts with the app and runs an overdue enabled search once. Model weights are never downloaded automatically.

Automatic discovery is enabled by default every **six hours**. Configure **Data sources → Recurring search schedule** to choose 3, 6, 12, or 24 hours, or pause. The schedule persists in SQLite. Searches use the newest federal posting dates first and include enabled approved pages. The dashboard shows the worker's actual status, the latest run, new/updated counts, and the next search in your browser's timezone. A partial run remains clearly labeled; a bounded collection is not full coverage.

The server and its internet connection must stay running. Closing the browser does not stop searches. Turning off this computer or stopping GrantIQ does; on restart, one overdue search runs instead of replaying every missed interval. For continuous operation, deploy to an always-on host or manage the server with your organization's service manager. The app does not install an OS startup service.

A dedicated worker checks the persistent schedule every 30 seconds. A per-instance scheduler lock prevents duplicate workers, and scheduled/manual/CLI refreshes share the ingestion lock. Busy searches retry after one minute; failed searches retry after 15 minutes; partial runs retain the normal schedule. A worker heartbeat older than 100 seconds is displayed as unavailable. A lost browser connection displays unavailable status rather than stale reassurance. Polling updates status only and never navigates away from unsaved forms. Pausing does not abort a search already in progress.

The CLI remains available for manual operation or an external scheduler. Pause the built-in schedule before replacing it with an external one. Use only one data directory/instance per host; distributed scheduling is outside this MVP.

## Architecture and schema

```text
grantiq/
  ingestion.py                 CLI and shared refresh coordinator
  app/
    main.py                    App factory, lifecycle, access control
    config.py                  Environment and data paths
    database.py                Portable engine/session setup
    security.py                Session secret, CSRF, login throttling
    schemas/domain.py          Validated adapter/profile/scoring contracts
    models/__init__.py         SQLAlchemy tables and relationships
    routes/web.py              Pages, forms, filters, CSV, refresh endpoint
    routes/research.py         Approved sources and evidence-review forms
    routes/schedule.py         Recurring schedule controls and live status
    services/
      eligibility.py           Hard gates and conservative review checks
      scoring.py               Deterministic components and confidence
      embeddings.py            Local MiniLM with explicit fallback
      deduplication.py         URL normalization and identity fingerprints
      repository.py            Persistence and profile rescoring
      verification.py          Verified facts, source revisions, review expiry
      scheduler.py             Persistent search worker, heartbeat, retry/recovery
    sources/
      base.py                  Adapter contract and bounded HTTP transport
      grants_gov.py            Official search2/fetchOpportunity adapter
      generic_scraper.py       Approved single-page adapter
    templates/                 Jinja2 HTML, reusable macros
    static/                    Local CSS and refresh-status script
config/
  organization.yaml            Initial profile, editable later in the app
  sources.yaml                 Administrator-managed approved pages
scripts/refresh_grants.py
tests/
requirements.txt
requirements-dev.txt
.env.example
Dockerfile
compose.yaml
```

| Table | Main columns and relationships |
|---|---|
| `organizations` | `id` PK, `profile` JSON, `updated_at` timestamp. Validated mission, interests, geography, budgets, scoring settings. |
| `grants` | `id` PK, `fingerprint` unique, title/funder/description/eligibility text, award min/max/estimated floats, open/deadline dates, status, discovery/check timestamps, `details` JSON for normalized variable source facts. |
| `source_records` | `id` PK, `grant_id` FK, source/source ID unique pair, official URL, last check, raw text. Several sources may refer to one canonical grant. |
| `grant_assessments` | `grant_id` PK/FK, indexed fit score and eligibility status, confidence, result JSON containing components, reasons, warnings, checks, semantic metadata, and scoring timestamp. |
| `pipeline_entries` | `grant_id` PK/FK, status, notes, assignee, requested amount, staff application deadline, submission date, final result, updated timestamp. |
| `refresh_runs` | `id` PK, start/end, status/source, found/added/updated/expired/rejected counts, errors JSON, per-source HTTP and normalization statistics. |
| `search_schedule` | Singleton enabled flag, interval, next run, heartbeat, last start/finish/status/error. Survives server restarts. |
| `approved_sources` | Public page URL (unique), funder name, enabled flag, terms approval, reviewer, permission reference, CSS selectors JSON, updated timestamp. |
| `grant_reviews` | Grant FK, verified facts JSON, source revision hash, evidence URL and notes, reviewer, review timestamp, valid-until date, verified/withdrawn action. Append-only through the application. |

The source ID is authoritative for a refreshed record. Cross-source matching uses normalized title + funder + deadline only when those fields are known. URL matching also checks source, title, and cycle deadline so shared listing pages do not collapse unrelated grants. Revised identity fields update the fingerprint. If a revision collides with another saved canonical grant, both staff histories remain intact and a review warning is recorded.

SQLite uses foreign keys, WAL, and bounded lock waits. The models use portable SQLAlchemy/JSON types rather than SQLite-specific SQL. To use a fresh PostgreSQL database, install `psycopg[binary]`, set `DATABASE_URL=postgresql+psycopg://...`, and start the app. Moving existing SQLite records requires an explicit data migration, and future schema revisions should use a migration tool such as Alembic; `create_all` initializes tables but does not migrate existing schemas.

This MVP uses one organization, a shared staff/admin password for hosted mode, one server process, and a shared data directory. For multiple replicas, add a database-backed/distributed job lock and a durable queue before scaling. Dashboard filtering is in Python after loading records and is suitable for a small nonprofit's initial catalog; larger catalogs should push JSON/filter queries into database indexes and add pagination.

## Exact scoring formula

Eligibility runs first. Any hard disqualifier sets **all components and total to 0**, with `INELIGIBLE` displayed. Missing material facts produce `Needs Review`, overriding recommendation labels. Otherwise the statuses are `Likely Eligible` or `Eligible` according to confirmed conditions.

Let `K` be normalized keyword overlap and `S` the local model's cosine similarity, clamped to `[0,1]` for points:

```text
Mission fraction = 0.65 × S + 0.35 × K
Fit score = sum(configured weight × component fraction), rounded to 2 decimals
Default weights = mission 30 + geography 20 + population 15 + funding 10
                + program 10 + past giving 10 + readiness 5
```

Keyword overlap uses normalized subject tokens, a small documented synonym map, and overlap divided by the smaller token-set size. The model receives the organization mission/description/programs/interests and the grant title/description/program areas/categories. MiniLM has a finite input window, so this is an MVP semantic signal rather than an exhaustive reading of long funding announcements.

| Component | Rule |
|---|---|
| Mission | 65% local cosine, 35% keyword coverage. Without embeddings only the 35% keyword share earns points. |
| Geography | Exact local overlap 20; statewide 17; confirmed regional 14; national U.S. 10; unclear 5; incompatible 0 plus eligibility gate. County overlaps are not inferred merely from a shared state. |
| Population | Token overlap against served populations; incomplete source/profile population metadata receives 25% of the weight. Explicit project restrictions require review. |
| Funding | Complete range meeting preferences 10; a useful reported one-sided amount 9; overlapping but smaller/larger estimate 7; unknown 4; incompatible range 0 and a gate. |
| Program | Overlap of reported categories/programs with organizational programs/interests; absent source fields receive 20% of the weight. |
| Past giving | Attributed recipient name + public evidence URL + relevant giving details are required. Best relevant overlap controls points; no evidence = 0. Phase 1 does not collect 990 data. |
| Readiness | More than 45 days = 5; 30–45 = 4; 15–29 = 3; fewer than 15 = 1; expired or forecasted = 0. Unknown deadline = 1; explicitly open rolling deadline = 4. Three thresholds and minimum preparation days are editable. |

Recommendation bands: 90–100 Exceptional; 80–89 Strong; 70–79 Good; 60–69 Possible; 40–59 Low Priority; below 40 Poor. Bands use the actual unrounded-to-integer score; displayed scores preserve up to two decimal places.

Confidence is a completeness index: eligibility text 10 + applicant types 10 + geography 15 + deadline 15 + funding 15 + program/categories 15 + direct application link 10 + named funder 10. It does not measure the chance of winning or guarantee that source assertions are accurate. A high confidence does not override eligibility review.

## Approved web sources

Open **Data sources → Add funding page**. Enter a public page describing one opportunity, record who reviewed its terms, and enable it for the next refresh. Saving validates its public address but does not fetch the page. You can save a disabled draft before approval. Edit or disable sources from Data sources; disabling preserves collected grants and staff work. Advanced extraction rules accept CSS selectors for confirmed page fields. Managed pages keep a stable source identity when their display name changes.

Administrators can alternatively edit `config/sources.yaml`. Enabled database and YAML sources are combined during refresh, with duplicate URLs collected once. Enable a public page only after an administrator reviews its actual terms:

```yaml
sources:
  - name: Your approved foundation
    url: https://approved-foundation.example/grants/specific-opportunity
    parser: generic
    enabled: true
    terms_reviewed: true
    selectors:
      title: h1
      description: main
      eligibility: .eligibility
      deadline: time.deadline
      award_min: .award-min
      award_max: .award-max
      application_url: a.apply
```

The URL above is an example, not a configured source. Each URL must represent one grant; the adapter never follows links across a site or splits a listing page into guessed grants. It respects robots rules and delays, identifies GrantIQ, caches pages for six hours, limits response sizes, retries temporary failures, and refuses missing/disallowed robots directives, nonpublic IP addresses, redirects, login controls, and detected access challenges. It pins validated public IPs while preserving TLS hostname checks to prevent DNS rebinding. It cannot automatically determine website terms; `terms_reviewed` records the administrator's review.

Extraction is deliberately conservative. Optional selectors support applicant types, locations, geographic scope, populations, categories, programs, and status in addition to the fields above. List selectors can match multiple elements; scope and status require recognized exact values. Unconfirmed details remain unknown. Add specialized Florida, county, hospital, and foundation adapters by implementing `GrantSource.fetch_grants()` and `normalize_grant()` and registering them in `configured_sources()`.

## Verify grant facts with evidence

Open an opportunity and choose **Verify source facts**. Read the official announcement, select only the fields you confirmed, and supply the evidence URL, supporting notes, your name, and a recheck date (up to 180 days). Saving recalculates eligibility, fit, and completeness from the effective facts. Staff cannot directly edit scores or eligibility verdicts.

Each verification is a new history entry, separate from the original imported facts. The latest verification replaces the previous set of verified fields; unchecked fields use imported values. A changed source revision or expired recheck date stops the prior corrections from applying and requires renewed review. A routine source recheck timestamp alone does not invalidate evidence. **Withdraw verified facts** returns assessment to imported facts while retaining the history. Passed deadlines still close opportunities.

Reviewer names are staff-entered attribution under the shared workspace login, not independently authenticated identities. Evidence links are recorded for staff and are not automatically fetched or judged for accuracy. Verification is not a substitute for reading the complete official announcement.

Official API references: [search2](https://www.grants.gov/api/common/search2), [fetchOpportunity](https://www.grants.gov/api/common/fetchopportunity), and the [API guide](https://www.grants.gov/api/api-guide). Both discovery endpoints are key-free. No Candid scraping is used.

## Access and deployment

Local mode accepts only loopback clients and expected hosts. For a shared server or Docker, copy `.env.example` to `.env` and set:

```dotenv
GRANTIQ_ADMIN_PASSWORD=<your-private-workspace-password>
GRANTIQ_SECRET_KEY=<a-random-secret-at-least-32-characters-long>
GRANTIQ_ALLOWED_HOSTS=localhost,127.0.0.1,grants.your-organization.org
GRANTIQ_SECURE_COOKIES=true
```

Use `GRANTIQ_SECURE_COOKIES=false` only for local HTTP, including local Docker. Set it true behind HTTPS for shared access. Generate the session secret locally with `python -c "import secrets; print(secrets.token_hex(32))"`. Keep `.env` and `data/` private and out of version control. Use TLS at the reverse proxy. Do not expose an unauthenticated loopback app through a proxy; configure the password first. The default command disables trusted forwarding headers.

Hosted mode protects dashboard, settings, notes, exports, and mutations behind sign-in. The MVP has one shared authorized staff role; individual accounts, role separation, and a comprehensive audit log of all staff edits are future hardening. Sessions have an eight-hour lifetime, signed HttpOnly cookies, CSRF protection, host validation, and bounded login attempts. Jinja escapes source text, source links are validated, and CSV cells are neutralized against spreadsheet formula injection.

Docker:

```bash
# Configure .env password + secret first (local Docker still needs these).
docker compose build
docker compose run --rm grantiq python -m grantiq.app.services.embeddings --download
docker compose up -d
```

The volume preserves the database and model. The container runs as a non-root user and publishes to host loopback by default. Docker files are provided; Docker was not available for a container smoke test in this workspace. The application was run and tested on Windows with Python 3.12.

For backup, stop the app and refresh jobs before copying the SQLite database, or use SQLite's online backup API. Do not copy a live WAL-mode `.db` alone. Save organization configuration and the database; downloaded model weights can be regenerated. Restore into a separate data directory and verify before replacing live data.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The normal test run uses injected embeddings and mock transports, requiring no external services. It covers excellent/weak matches, unknowns, incompatible geography, expired grants, duplicates, source failures, and persisted staff changes. To also verify the real cached model:

```powershell
$env:GRANTIQ_TEST_LOCAL_MODEL = '1'
python -m pytest -q
```

```bash
GRANTIQ_TEST_LOCAL_MODEL=1 python -m pytest -q
```

If a constrained Windows temp folder prevents pytest fixtures from being created, use `python -m pytest -p no:cacheprovider --basetemp <a-new-workspace-test-folder>`.



## Public repository and local research

The public repository contains application code and safe starter configuration. Internal PDFs, prospect decisions, historical funder amounts, meeting notes, and private integration tests are excluded through .gitignore. They remain available in the local working project.

Without private configuration files, the app uses config/examples/: a small public keyword vocabulary and empty prospect/funder registers. To add your own research, copy those templates into config/ and edit the local copies. These filenames are ignored by Git. Adding a funder register later still triggers its initial import; empty public defaults do not consume that import.

The /research page shows actual configured counts and only links installed reference PDFs. The /sprint-review route displays a public architecture overview when a local presentation is absent. Internal meeting handouts return 404 when not installed.

## Development

See CONTRIBUTING.md for test commands and code responsibilities. GitHub Actions runs the public tests on Python 3.12 with pinned dependencies. The optional local-model check requires downloaded weights; normal tests use fixtures. Docker configuration is provided but has not been validated on this machine.
