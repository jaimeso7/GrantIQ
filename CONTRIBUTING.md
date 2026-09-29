# Working on GrantIQ

Use Python 3.12 and an isolated virtual environment. Install the tested package versions:

```bash
python -m pip install -r requirements-dev.txt -c requirements-lock.txt
python -m pip check
python -m pytest -q
```

`requirements.txt` lists direct runtime dependencies. `requirements-dev.txt` adds pytest. `requirements-lock.txt` constrains direct and supporting packages to the inspected Windows environment; it is a version snapshot, not a hash-verified lock or proof of compatibility with every operating system. Docker and CI use the same constraints. Their first remote builds still need validation.

The default suite skips the optional real-model test and does not download model weights. To include it, prepare the model with the README command, then run:

```powershell
$env:GRANTIQ_TEST_LOCAL_MODEL = '1'
python -m pytest -q
```

## Code responsibilities

- `grantiq/app/routes/`: HTTP inputs, validation, responses, and presentation delivery.
- `grantiq/app/services/`: scheduling, matching, evidence review, staff context, and persistence.
- `grantiq/app/sources/`: source-specific retrieval and normalization.
- `grantiq/app/models/` and `schemas/`: database tables and validated domain values.
- `grantiq/ingestion.py`: refresh orchestration and CLI entrypoint.

Keep eligibility, numerical fit, source confidence, and staff decisions separate. Refreshes must preserve staff-owned pipeline and review history. Unknown eligibility must remain unknown. Model failures must disclose keyword fallback.

Staff context is indexed once per SQLAlchemy session. Call `invalidate_staff_context(session)` when changing profile or research keys inside a session that already rendered grants. `set_profile()` and the initial import already invalidate this cache. Do not introduce a process-global cache containing one organization's working decisions.

Bulk reassessment eagerly loads assessment and review relationships. Regression tests limit its query count to prevent a query for every grant. Keyword batches deduplicate terms without regard to case and preserve the six core terms.

## Pull request checks

Describe the user-visible change and its validation. Add regression tests when fixing behavioral bugs. Run relevant focused tests, then the complete suite after the final code change. Do not change scoring weights or staff filtering behavior as an incidental refactor.

GitHub Actions runs the default suite on Python 3.12, with read-only repository permissions and actions pinned to commit IDs. Workflow structure follows [GitHub's Python testing guidance](https://docs.github.com/en/actions/tutorials/build-and-test-code/python). A local pass does not mean a remote Actions run has completed.

## Repository contents

Never commit `.env`, databases, model caches, virtual environments, logs, or session secrets. The ignore files exclude these from both Git and container builds.

Internal source PDFs, prospect notes, funder records, and meeting documents stay in ignored local files. Public configuration templates live in config/examples/. Never force-add private files. The original internal Git history is retained outside this public repository so earlier commits cannot expose those files.

No license is selected automatically. Repository owners should choose one before distributing the application as open-source software.
