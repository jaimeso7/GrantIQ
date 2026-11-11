# Node migration

Deployment branch: `codex/railway`. Railway is the selected hosting platform.
The legacy Python implementation remains for reference and rollback. The native
Node application uses Express, PostgreSQL, a recurring discovery worker and local
MiniLM semantic matching. It does not start a Python subprocess.

See [RAILWAY.md](RAILWAY.md) for deployment, [DATA-MIGRATION.md](DATA-MIGRATION.md)
for the read-only Python importer, and [GRANT-WATCH.md](GRANT-WATCH.md) for the
foundation discovery and scoring policy. Node SQLite is for local use; production
requires PostgreSQL. Node-only edits are not present in an old Python snapshot.

The current workspace is stored as one transaction-protected database document.
Individual staff accounts and multi-organization scaling are future work.
Validate actual host resource use, backups/restoration, HTTPS login, persistence
and unattended scheduling on Railway before a production handoff.
