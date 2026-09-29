"""Refresh from trusted adapters: python -m grantiq.ingestion."""
import argparse
import logging
import os
from datetime import datetime, timezone
from filelock import FileLock, Timeout
from sqlalchemy import select
from .app.config import DATA_DIR, ROOT
from .app.database import initialize, SessionLocal
from .app.models import RefreshRun
from .app.schemas import GrantRecord
from .app.services.repository import get_profile, upsert_grant, rescore_all

log = logging.getLogger("grantiq.ingestion")

def configured_sources(max_records=100, profile=None, session_factory=SessionLocal):
    import yaml
    from .app.sources.grants_gov import GrantsGovSource
    from .app.services.research_context import keyword_plan
    from .app.models import SearchCursor
    with session_factory() as cursor_session:
        cursor = cursor_session.get(SearchCursor, 1)
        position = cursor.position if cursor else 0
    keywords, next_position, pool_size = keyword_plan(profile, position)
    official = GrantsGovSource(keywords=keywords, max_records=max_records)
    official.stats.update(search_terms=keywords, keyword_cursor=position, rotating_pool_size=pool_size)
    yield official
    # A full HTTP failure retains the batch for retry; successful searches rotate.
    if official.stats['http_requests'] > official.stats['http_failures']:
        with session_factory() as cursor_session:
            cursor = cursor_session.get(SearchCursor, 1)
            if cursor is None:
                cursor = SearchCursor(id=1)
                cursor_session.add(cursor)
            cursor.position = next_position
            cursor_session.commit()
    path = ROOT / "config" / "sources.yaml"
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else []
    if isinstance(entries, dict):
        entries = entries.get("sources", [])
    from .app.models import ApprovedSource
    with session_factory() as source_session:
        database_sources = source_session.scalars(select(ApprovedSource).where(ApprovedSource.enabled.is_(True))).all()
        entries = [*(entries or []), *[{"name": row.name, "url": row.url, "source_key": f"Approved page {row.id}", "parser": "generic", "enabled": row.enabled, "terms_reviewed": row.terms_reviewed, "selectors": row.selectors} for row in database_sources]]
    seen_urls = set()
    for item in entries or []:
        if item.get("enabled", False) and item.get("parser") == "generic" and item.get("url") not in seen_urls:
            seen_urls.add(item.get("url"))
            from .app.sources.generic_scraper import GenericScraperSource
            yield GenericScraperSource(item)

def run_refresh(*, sources=None, session_factory=SessionLocal, embedder=None, max_records=100):
    from .app.services.scoring import score_grant
    initialize(session_factory.kw.get("bind"))
    lock = FileLock(str(DATA_DIR / "refresh.lock"))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return {"status": "busy", "errors": ["A refresh or settings update is already running."]}
    run_id = None
    try:
        with session_factory() as session:
            # Recover audit rows abandoned by a terminated process; the file lock
            # proves no refresh still owns this instance's data directory.
            for old in session.scalars(select(RefreshRun).where(RefreshRun.status == "running")):
                old.status = "interrupted"
                old.finished_at = datetime.now(timezone.utc)
                old.errors = [*old.errors, "Previous refresh stopped before completion."]
            profile = get_profile(session)
            run = RefreshRun()
            session.add(run)
            session.commit()
            run_id = run.id
        errors, counts, source_stats = [], dict(found=0, added=0, updated=0, expired=0, rejected=0), {}
        for adapter in (sources if sources is not None else configured_sources(max_records, profile, session_factory)):
            name = getattr(adapter, "name", adapter.__class__.__name__)
            try:
                for raw in adapter.fetch_grants():
                    counts["found"] += 1
                    try:
                        record = raw if isinstance(raw, GrantRecord) else adapter.normalize_grant(raw)
                        assessment = score_grant(record, profile, embedder=embedder)
                        with session_factory() as session:
                            _, added = upsert_grant(session, record, assessment, profile=profile, embedder=embedder)
                            session.commit()
                        counts["added" if added else "updated"] += 1
                        if counts["found"] % 10 == 0:
                            with session_factory() as progress_session:
                                progress = progress_session.get(RefreshRun, run_id)
                                for key, value in counts.items():
                                    setattr(progress, key, value)
                                progress_session.commit()
                    except Exception as exc:
                        counts["rejected"] += 1
                        errors.append(f"{name}: record rejected: {type(exc).__name__}: {str(exc)[:300]}")
                        log.exception("Record failed source=%s", name)
            except Exception as exc:
                errors.append(f"{name}: {type(exc).__name__}: {str(exc)[:300]}")
                log.exception("Source failed source=%s", name)
            finally:
                if callable(getattr(adapter, "close", None)):
                    adapter.close()
            errors.extend(f"{name}: {str(e)[:300]}" for e in getattr(adapter, "errors", []))
            counts["rejected"] += int(getattr(adapter, "stats", {}).get("rejected", 0))
            source_stats[name] = getattr(adapter, "stats", {})
            with session_factory() as session:
                run = session.get(RefreshRun, run_id)
                for k, v in counts.items():
                    setattr(run, k, v)
                run.errors, run.source_stats = errors.copy(), source_stats.copy()
                session.commit()
        with session_factory() as session:
            # Recheck existing deadlines even if every remote source failed.
            counts["expired"] = rescore_all(session, profile, embedder=embedder)
            run = session.get(RefreshRun, run_id)
            for k, v in counts.items():
                setattr(run, k, v)
            run.errors, run.source_stats = errors, source_stats
            run.finished_at = datetime.now(timezone.utc)
            run.status = ("partial" if counts["added"] + counts["updated"] else "failed") if errors else "completed"
            session.commit()
            result = {"id": run.id, "status": run.status, **counts, "errors": errors, "source_stats": source_stats}
            log.info("Refresh completed %s", result)
            return result
    except Exception as exc:
        log.exception("Refresh pipeline failed")
        if run_id:
            with session_factory() as session:
                run = session.get(RefreshRun, run_id)
                run.status, run.finished_at = "failed", datetime.now(timezone.utc)
                run.errors = [*run.errors, f"Pipeline: {type(exc).__name__}: {str(exc)[:300]}"]
                session.commit()
        raise
    finally:
        lock.release()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-records", type=int, default=int(os.getenv("GRANTIQ_MAX_RECORDS", "100")))
    args = parser.parse_args()
    if not 1 <= args.max_records <= 5000:
        parser.error("--max-records must be between 1 and 5000")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    result = run_refresh(max_records=args.max_records)
    print(result)
    return 1 if result["status"] in {"failed", "partial"} else 0

if __name__ == "__main__":
    raise SystemExit(main())
