# Deploy GrantIQ to SiteGround Node.js Projects

Prepared October 21, 2026. This branch is a native Node.js implementation: no Python server, virtual environment, or Python package installation is used at runtime.

## What to select

SiteGround's announcement confirms Node.js Projects on GrowBig, GoGeek, and Cloud, with GitHub/ZIP deployment, environment variables, HTTPS, and managed PostgreSQL. StartUp does not include Node.js Projects. The application is prepared for this service; a deployment on your actual account remains to be verified.

Official references:
- https://www.siteground.com/blog/hosting-node-js-projects-with-siteground
- https://www.siteground.com/kb/node-js-available

In Client Area → Websites → Node.js Projects, add a project. Use either the prepared source ZIP or a GitHub branch that contains this migration. Connecting the old Python-only main branch will not deploy this Node version. GitHub automatic deployment should be enabled only after the Node branch and environment are ready.

| Setting | Value |
| --- | --- |
| Framework | Express / custom Node.js server (not a static site) |
| Node | 22.13 or newer in the 22 line, or Node 24 |
| Package manager | npm |
| Project root | Repository / ZIP root, containing package.json |
| Dependency install | `npm ci` (or `npm ci --omit=optional` for keyword-only mode) |
| Build command | `npm run build` |
| Start command / package script | `npm start` |
| Entry point if requested | `node/server.js` |
| Output directory | Project root; no dist folder / static build output |
| Listening port | Uses SiteGround's `PORT` environment value; default 3000 |

SiteGround's setup screen may label the Express preset's startup fields differently. Confirm its generated launch command invokes the package start script and routes its assigned port. Do not select a frontend-only preset. The build command verifies application syntax; it does not connect to the database or download models.

## Create persistent storage before starting

Create a **PostgreSQL** database and dedicated user in Site Tools. Keep its credentials private. The Node app uses a separate `grantiq_node_workspace` table and creates it at first startup. It does not alter the legacy Python tables.

Configure these as runtime environment variables in Site Tools:

```dotenv
NODE_ENV=production
HOST=0.0.0.0
GRANTIQ_ALLOWED_HOSTS=your-exact-temporary-domain.example
GRANTIQ_ADMIN_PASSWORD=choose-a-long-private-workspace-password
GRANTIQ_SECRET_KEY=generate-a-random-secret-at-least-32-characters
GRANTIQ_DATABASE_URL=postgresql://database-user:encoded-password@database-host:5432/database-name
GRANTIQ_DATABASE_SSL=disable
GRANTIQ_SCHEDULER=true
GRANTIQ_MAX_RECORDS=100
GRANTIQ_SEMANTIC_MODE=keyword
```

Use the actual database host/port provided by SiteGround. URL-encode special characters in database credentials. Set `GRANTIQ_DATABASE_SSL=require` when your database endpoint requires trusted TLS; do not disable certificate verification. The application's HTTPS connection is independent of database TLS.

Generate a secret locally with:

```sh
node -e "console.log(require('node:crypto').randomBytes(32).toString('hex'))"
```

Keep the same secret across deployments so staff sessions are stable. Never commit credentials, `.env.node`, database snapshots, or private research. Production startup refuses to run without PostgreSQL, a password, a sufficiently long session secret, and explicit allowed hosts. The shared staff password is the MVP access model; named accounts and individual permissions are not implemented.

When connecting a custom domain, add its exact hostname to `GRANTIQ_ALLOWED_HOSTS` (comma-separated if retaining the temporary domain). Access the app through HTTPS; production session cookies are Secure. The app validates the actual Host header and does not trust arbitrary forwarding headers.

## Matching model choices

**Keyword mode** runs without a model download or optional native libraries. It visibly reports `keyword_fallback`; only 35% of the mission weight can be earned. This is a reduced matching mode, not equivalent semantic scoring.

**Local MiniLM mode** runs in Node using Transformers.js, with no paid AI API. It was exercised successfully on the development computer. Its RAM, CPU, native-library support, and cache location still need testing on your SiteGround plan:

1. Install optional dependencies with normal `npm ci`.
2. Set `GRANTIQ_MODEL_CACHE` to an administrator-approved, private persistent directory outside disposable deployments, or arrange to download weights during each deployment.
3. Run `npm run model:download` over the supported project SSH environment. Confirm the `Ready: MiniLM, 384 dimensions` result.
4. Set `GRANTIQ_SEMANTIC_MODE=local`, restart, and run `npm run rescore` to update stored scores.
5. Inspect an opportunity: its scoring mode should be `local_transformers_js`. If loading fails, the app discloses keyword fallback.

The ONNX model cache is not the Python model cache; download it separately. Do not assume shared hosting has enough resources just because it accepts Node.js. Native runtime threads are limited to one per inference session. No GPU is required.

## Move existing work safely

A public GitHub checkout contains safe starter settings, not your staff database, research notes, or Ashley's attachments. Do not publish those to make the new site look populated.

For an existing Python workspace:

1. Stop Python refresh jobs and the Python app, or make a consistent SQLite backup using SQLite's backup API. Do not copy a live WAL-mode database file alone.
2. Keep a private backup and transfer only the authorized database snapshot through a private channel to a non-public path. Do not place it in your GitHub repository or deployment ZIP.
3. Pause the destination scheduler with `GRANTIQ_SCHEDULER=false` while importing into a new, unused Node database.
   Transfer the authorized `search_keywords.json` and `existing_funders.json` privately into `config/` **before the first Node startup** if you need the original keyword library and funder aliases. These are file-based in Python and are not contained in its SQLite database. Node seeds them into persistent storage so subsequent deploys do not need to retain those files. Never include them in the public ZIP or Git repository.
4. From the project directory with the production environment configured, run:

```sh
npm run import:python -- /private/path/grantiq-snapshot.db
```

5. Verify organization settings, grant count, saved pipeline entries and notes, approved sources, and research decisions. The import refuses to overwrite an occupied destination and leaves the source file read-only.
6. Staff evidence history is preserved, but legacy verification hashes require renewed review before corrections are reapplied. Imported search scheduling is paused deliberately. Enable it only after validation.
7. Restore `GRANTIQ_SCHEDULER=true`, restart, and choose the desired schedule in Data sources.

The first startup can seed private config files if installed separately before database initialization. Later changes to those files do not overwrite staff decisions. Profile exclusions, imported research prospects, sources and the search cursor are stored in PostgreSQL. Original research PDFs and private presentation files are not served by the Node app; keep them in your team's existing private document location.

## Deployment acceptance checks

- `/health` returns `status: ok` without exposing credentials.
- Opening `/` while signed out redirects to login; incorrect passwords fail.
- Sign in over HTTPS and save a test organization setting and pipeline note.
- Restart/redeploy, sign in again if needed, and confirm both values persist.
- Run Search now; verify last-run counts and any partial/failure messages.
- Choose a schedule; verify the heartbeat, next due time, and a completed scheduled run while your own PC is off.
- Confirm semantic or keyword mode explicitly; test model loading after a redeploy if enabled.
- Review backups and test restore to a separate PostgreSQL database before launch.

Database-backed leases prevent simultaneous refreshes across app processes. They expire after an interrupted worker; the next worker records an interrupted run. One overdue search runs on recovery, rather than replaying every missed interval. The worker runs within the web process: if SiteGround suspends/restarts it, searches resume only when the process runs again. Verify actual behavior in your account before promising uninterrupted searching. If using an external scheduler with `npm run refresh`, set `GRANTIQ_SCHEDULER=false` to avoid two scheduling mechanisms.

## Updates, costs, and limits

After launch, a push to the connected branch can rebuild and redeploy the app. Staff open the same URL; they do not reinstall anything. Database backups remain necessary before changes. The Node code has its own locked npm dependencies and test workflow.

Node.js Projects are included in eligible SiteGround plans according to the linked announcement; this does not make the hosting plan free. Check your account's renewal price, resource allowance, database capacity, optional upgrades, and domain renewal. Setup, support, backups and any resource upgrade are additional project costs. This migration does not purchase or change a SiteGround subscription.

The storage layout is deliberately a single locked workspace document for this small MVP. It preserves atomic staff changes and serializes concurrent writes; it is not designed for large multi-organization workloads. At larger volumes, split records into indexed relational tables before promising scale. Generic approved sources fetch one page and do not crawl entire sites. They respect robots/access controls, but their terms still require human review. Native model inference uses the same MiniLM family as Python, not a promise of bit-for-bit floating-point identity.
