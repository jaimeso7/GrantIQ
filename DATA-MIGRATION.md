# Move existing work safely

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
