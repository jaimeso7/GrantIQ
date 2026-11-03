# Node migration verification — October 21, 2026

Branch: `codex/siteground-node`. The Python implementation is retained for reference and rollback. No SiteGround account was changed and no live deployment was made.

## Implemented

- Native Express server and server-rendered, responsive grayscale interface; no Python runtime calls.
- Organization settings, discovery filters, grant details, pipeline, research decisions, source editing, evidence reviews and CSV export.
- Ported eligibility and all seven scoring components, including conservative unknown handling and keyword fallback cap.
- Transformers.js MiniLM inference, with explicit model preparation, bounded in-memory embedding cache and one inference thread.
- Grants.gov full-detail retrieval and approved single-page sources with public-address/DNS validation and robots controls.
- Transactional PostgreSQL workspace storage for hosting; isolated SQLite storage for local use.
- Recurring schedules and expiring database leases, persisted activity, retry after failure and interrupted-run recovery.
- Shared-password login, signed expiring session cookies, host validation, CSRF checks and throttling.
- Read-only legacy SQLite import; unused-destination guard; imported schedule paused and old evidence requires renewal.
- SiteGround configuration guide and Node launcher.

## Completed checks

- 61 Node tests passed; 1 PostgreSQL integration test skipped locally because no test PostgreSQL server was available. The committed CI workflow provisions PostgreSQL and enables it; that remote run has not been claimed as completed.
- 30 of the Node tests compare the numerical and eligibility results against the Python reference using synthetic records.
- Legacy Python suite: 145 passed, 1 optional model test skipped. A workspace-local temp directory was used because the default temporary directory caused fixture failures on Windows.
- `npm run build` passes; npm dependency audit reports zero known vulnerabilities at the time checked.
- Real Grants.gov search and detail fetch succeeded through the Node adapter.
- Real MiniLM model download and 384-dimensional inference succeeded. A new process loaded cached weights and returned a finite similarity without downloading again.
- Existing local data was copied consistently and imported into a separate Node workspace; staff pipeline entries were retained. No original SQLite data was modified.
- Headless Edge browser checks: desktop discovery/detail pages and mobile source page rendered; no browser JavaScript errors or horizontal overflow in those views.

## Deliberate differences / remaining deployment validation

- SiteGround uses PostgreSQL rather than relying on deployment-directory files. The MVP stores a single workspace document under a transaction lock; high-volume/multi-organization scaling requires a relational redesign.
- Historical Python review evidence is retained but requires renewed validation because revision encodings differ. Scoring explanations use equivalent, shorter wording; ONNX floating-point results are not guaranteed bit-identical to Python.
- Imported research decisions and exclusions are available. Original private PDF download routes and internal sprint handouts are not exposed by the Node version; its sprint route is a public architecture overview.
- The old Python Docker configuration remains a legacy path; SiteGround uses package.json instead.
- SiteGround runtime/version selection, PostgreSQL connectivity, TLS, data survival through redeploys, actual scheduled execution, host resource limits and model cache persistence must be checked on the target account before launch.
- Individual user accounts, roles, automated application submission, comprehensive foundation crawling and emailed alerts remain outside the existing MVP scope.

The deployment ZIP is built from an explicit public-file allowlist. Credentials, local SQLite databases, private configuration, original research PDFs and internal notes are excluded. A source ZIP is not a backup of staff data.
