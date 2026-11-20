"""Monthly refresh of 990-PF foundation research.

The research pipeline (analysis/irs990/report.py) downloads IRS archives
(several GB on the first run) and runs the embedding model, so it runs as a
separate process: a crash or memory spike there cannot take the web app down,
and a checkout without the pipeline simply reports it as unavailable. When the
run succeeds, its JSON is imported in the same way as on startup.
"""
import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from filelock import FileLock, Timeout

from ..config import DATA_DIR, ROOT
from ..models import Irs990Schedule
from .foundations import import_prospects, prospects_file

log = logging.getLogger(__name__)
PIPELINE = ROOT / "analysis" / "irs990" / "report.py"
INTERVAL_DAYS = 30
TIMEOUT_SECONDS = 2 * 3600  # a first run downloads ~2GB
RETRY_AFTER = timedelta(hours=6)


def now_utc():
    return datetime.now(timezone.utc)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def ensure_irs990_schedule(session, now=None):
    row = session.get(Irs990Schedule, 1)
    if row is None:
        # First check a day after setup: startup already imports any existing results.
        row = Irs990Schedule(id=1, enabled=True, interval_days=INTERVAL_DAYS,
                             next_run_at=(now or now_utc()) + timedelta(days=1))
        session.add(row)
        session.commit()
    return row


def irs990_status(session, now=None):
    now = now or now_utc()
    row = ensure_irs990_schedule(session, now)
    stamp = lambda value: utc(value).isoformat() if value else None
    if not PIPELINE.is_file():
        status = "Pipeline not installed"
    elif row.last_status == "running":
        status = "Checking IRS now"
    elif not row.enabled:
        status = "Paused"
    elif utc(row.next_run_at) <= now:
        status = "Check due"
    elif row.last_status == "failed":
        status = "Retry scheduled"
    else:
        status = "Scheduled"
    return {"enabled": row.enabled, "interval_days": row.interval_days, "status": status,
            "next_run_at": stamp(row.next_run_at) if row.enabled else None,
            "last_started_at": stamp(row.last_started_at), "last_finished_at": stamp(row.last_finished_at),
            "last_status": row.last_status, "last_error": row.last_error, "summary": row.last_summary or {}}


def claim_if_due(session, now):
    """Mark the run as started and schedule the next one. True if the caller should run it."""
    row = ensure_irs990_schedule(session, now)
    if row.last_status == "running":
        # Only reached after a restart: the process that owned the run is gone.
        row.last_status, row.next_run_at = "interrupted", now
    if not (row.enabled and utc(row.next_run_at) <= now and PIPELINE.is_file()):
        session.commit()
        return False
    row.last_started_at, row.last_status, row.last_error = now, "running", ""
    row.next_run_at = now + timedelta(days=row.interval_days)
    session.commit()
    return True


def run_pipeline():
    """Run report.py in its own process. Returns (ok, message)."""
    try:
        result = subprocess.run([sys.executable, str(PIPELINE)], cwd=ROOT, capture_output=True,
                                text=True, timeout=TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        return False, f"The IRS refresh took longer than {TIMEOUT_SECONDS // 3600} hours and was stopped."
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-3:]
        return False, " · ".join(tail)[:1000] or f"Pipeline exited with code {result.returncode}"
    return True, ""


def execute(session_factory, clock=now_utc, runner=run_pipeline):
    """One complete refresh: run the pipeline, then import what it wrote."""
    summary, error = {}, ""
    try:
        with FileLock(str(DATA_DIR / "irs990.lock"), timeout=0):
            ok, error = runner()
            if ok:
                with session_factory() as session:
                    import_prospects(session, prospects_file())
                data = json.loads(prospects_file().read_text(encoding="utf-8"))
                summary = {**data.get("summary", {}), "foundations": len(data.get("prospects", [])),
                           "years": data.get("years", [data.get("year")])}
    except Timeout:
        ok, error = False, "Another IRS refresh is already running."
    except Exception as exc:
        log.exception("IRS 990 refresh failed")
        ok, error = False, f"{type(exc).__name__}: {str(exc)[:300]}"
    with session_factory() as session:
        row = ensure_irs990_schedule(session)
        row.last_finished_at = clock()
        row.last_status = "success" if ok else "failed"
        row.last_error = error
        if ok:
            row.last_summary = summary
        else:
            row.next_run_at = min(utc(row.next_run_at), clock() + RETRY_AFTER)
        session.commit()
