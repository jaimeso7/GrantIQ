# GrantIQ on Railway

Prepared October 25, 2026. This is deployment preparation, not evidence of a live Railway deployment. See [HOSTING-COMPARISON.md](HOSTING-COMPARISON.md) for stakeholder costs and responsibilities.

## Architecture

Staff browser → Railway HTTPS endpoint → one Node.js/Express service → PostgreSQL over Railway private networking. The Node process also runs the recurring grant-search worker. MiniLM runs on CPU inside the app, without a paid AI API. No Python service is needed.

`railway.json` explicitly selects `Dockerfile.railway`; the root `Dockerfile` still runs legacy Python. The Node image includes only application code, public starter configuration, and public model weights. It runs as the unprivileged `node` user. The database holds staff data; the application filesystem is disposable. The model is downloaded during image build and reused after restarts, so no app volume is required. Model download failure fails the build rather than silently shipping without the model.

## Initial deployment (developer)

1. Create a VIP-owned Railway Pro workspace, with VIP billing and at least two authorized administrators. Invite developers using their own accounts. Do not share the owner's login.
2. Connect the GitHub repository and select the migration branch **`codex/siteground-node`**, which now contains Railway support as well. Confirm it contains both this file and `railway.json`. Do not select the older Python-only main branch. Set the repository root as the service root.
3. Add the official PostgreSQL service in the same project/environment and region. Confirm its persistent volume. Start with 5 GB capacity; monitor database and backup growth. Keep the database private and disable unnecessary public TCP exposure. Do not attach the app's `railway.json` to the database service.
4. Generate the app's Railway domain. Supply the runtime variables below before deploying. A first automatic deployment may fail until these are present; production fails closed intentionally.
5. Build using the checked-in Railway configuration. It installs Node 22 dependencies, validates the app, and downloads/smoke-tests MiniLM during the Linux image build. No runtime start-command override is required. Let Railway provide `PORT`.
6. Initially set a **2 GB app RAM limit and 1 vCPU limit**, one replica. Allow PostgreSQL approximately **1 GB RAM** initially. These are starting limits, not measured consumption or fixed monthly charges. Observe peak RAM/CPU during a full search and rescore before reducing them. Keep Serverless/sleep disabled on both app and database for this deployment.
7. Complete the acceptance checks below before staff use or enabling the search schedule.

Runtime variables (enter real secrets only in Railway's variable manager):

```dotenv
NODE_ENV=production
HOST=0.0.0.0
GRANTIQ_DATABASE_URL=${{Postgres.DATABASE_URL}}
GRANTIQ_DATABASE_SSL=disable
GRANTIQ_ALLOWED_HOSTS=your-app.up.railway.app,healthcheck.railway.app
GRANTIQ_ADMIN_PASSWORD=<long-unique-staff-password>
GRANTIQ_SECRET_KEY=<random-secret-at-least-32-characters>
GRANTIQ_SCHEDULER=false
GRANTIQ_MAX_RECORDS=100
GRANTIQ_SEMANTIC_MODE=local
```

The reference variable assumes the database service is named `Postgres`; adjust the name to match. Verify the resolved database hostname ends in `.railway.internal`. `disable` above applies only to the encrypted Railway private network, not a public database endpoint. External database connections must use trusted TLS (`require`). Never paste a public database URL into the example or commit credentials.

Generate the session secret locally: `node -e "console.log(require('node:crypto').randomBytes(32).toString('hex'))"`. Keep it stable across deployments. Add a custom hostname to the exact allowed-host list when attaching your domain. Include `healthcheck.railway.app` because Railway sends readiness checks with that Host header; it does not bypass staff sign-in on private routes. `/health` checks database connectivity, not source availability or model readiness.

The image defaults to semantic matching. If memory is constrained, `GRANTIQ_SEMANTIC_MODE=keyword` avoids loading the model at runtime, but the mission score then earns only its 35% keyword share. Rescore after changing modes and tell stakeholders this is reduced matching, not equivalent quality. The image still contains public weights in keyword mode.

## Existing data and private research

GitHub is source code, not a database backup. A fresh deployment starts with public starter settings and no saved grants. Never bake the private SQLite database, staff notes, funder amounts, or research PDFs into the Docker image.

For a Python-to-Node migration, use the read-only importer described in [SITEGROUND.md](SITEGROUND.md#move-existing-work-safely), but use the Railway PostgreSQL destination. Keep both source and destination schedules paused. A developer can run the importer locally with authorized private config files and a consistent SQLite snapshot, using a temporary TLS-protected database connection to the new destination. Initialize with private config before the first app startup if it is needed for keyword/funder seeds. Disable temporary public database access afterward. Verify counts, pipeline notes and private research; never overwrite an occupied destination. A Railway shell session runs remotely; `railway run` supplies variables to a local process and does not make private Railway DNS reachable from a laptop.

If moving an already-populated Node PostgreSQL workspace, take a private `pg_dump` and restore into a new empty PostgreSQL database using a compatible PostgreSQL client. Preserve the original until validation. The current local Node SQLite store is not a PostgreSQL backup and must not be passed to the Python importer; a direct Node-SQLite transfer tool is not implemented. The original Python snapshot import does not include subsequent Node-only edits. Plan that transfer before cutover if staff have made new Node edits.

## Acceptance and maintenance

- Verify `/health` is healthy, anonymous private pages redirect to sign-in, and HTTPS login and a CSRF-protected save work on the final hostname.
- Save a test pipeline note, redeploy, and confirm persistence. Check scoring reports `local_transformers_js` after scoring a grant; health alone does not prove that.
- Complete Search now and review partial/failure messages. Once validated, set `GRANTIQ_SCHEDULER=true`, redeploy, then enable the desired interval in Data sources. Verify an unattended scheduled run while your PC is off. Imported schedules stay paused until explicitly enabled.
- Keep the web service awake. If a separate Railway cron worker is adopted later, disable the embedded scheduler and test the worker separately. No cron worker is configured here.
- Enable daily and weekly PostgreSQL volume backups. Test restoration into a separate environment, and keep periodic encrypted database exports under VIP control. A code rollback does not undo database changes. Daily backups alone allow up to roughly a day's data loss; assess point-in-time recovery if that is unacceptable.
- Set usage alerts (for example $25 and an agreed maximum budget). A hard usage limit stops workloads and searches when reached. It trades continuity for a spending cap. Do not treat the $20 Pro minimum as a cap.
- Assign a developer to review dependency updates, deployments, failed searches, capacity and database upgrades. Staff only need a browser for normal use. Use CI and a staging environment before production changes; extra staging services also incur usage.
- Review logs/metrics after each deploy. Railway readiness checks gate deployment but are not ongoing uptime monitoring; configure external monitoring and notification ownership separately.

## Verified here / still pending

The app already supports production PostgreSQL, assigned ports, signed secure cookies, CSRF checks, exact host validation and graceful shutdown. Railway configuration follows its published schema and healthcheck hostname. Local validation passed the build check and 62 tests, including Railway-host healthcheck, private-route authentication and Secure-cookie checks; one PostgreSQL integration test was skipped because no local PostgreSQL test server is configured. Docker is unavailable on the development machine, so the Linux container build, Railway HTTPS/proxy behavior, model RAM/CPU use, database restore and unattended scheduled run must still be validated on Railway. The CI workflow now includes a container build/model smoke check for the next published revision. No hosting purchase or live deployment has been performed.

Official references: [Configuration](https://docs.railway.com/config-as-code/reference), [healthchecks](https://docs.railway.com/deployments/healthchecks), [private networking](https://docs.railway.com/networking/private-networking), [serverless](https://docs.railway.com/deployments/serverless), [backups](https://docs.railway.com/volumes/backups).
