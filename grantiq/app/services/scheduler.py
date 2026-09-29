"""Persistent single-host recurring search with heartbeat and bounded recovery."""
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from filelock import FileLock, Timeout
from sqlalchemy import select
from ..config import DATA_DIR
from ..models import SearchSchedule, RefreshRun

log = logging.getLogger(__name__)
INTERVALS = (3, 6, 12, 24)

def now_utc():
    return datetime.now(timezone.utc)

def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value

def ensure_schedule(session, now=None):
    row = session.get(SearchSchedule, 1)
    if row is None:
        row = SearchSchedule(id=1, enabled=True, interval_hours=6, next_run_at=now or now_utc())
        session.add(row)
        session.commit()
    return row

def schedule_status(session, now=None):
    now = now or now_utc()
    row = ensure_schedule(session, now)
    latest = session.scalar(select(RefreshRun).order_by(RefreshRun.id.desc()).limit(1))
    alive = bool(row.heartbeat_at and (now-utc(row.heartbeat_at)).total_seconds() < 100)
    running = bool(latest and latest.status == "running")
    status = "Searching now" if alive and running else "Paused" if not row.enabled else "Worker unavailable" if not alive else "Scheduled"
    if alive and row.enabled and not running and utc(row.next_run_at) <= now:
        status = "Search due"
    if alive and row.enabled and not running and row.last_status == "failed":
        status = "Retry scheduled"
    def stamp(value):
        return utc(value).isoformat() if value else None
    return {"enabled": row.enabled, "interval_hours": row.interval_hours, "worker_alive": alive,
        "status": status, "next_run_at": stamp(row.next_run_at) if row.enabled else None,
        "heartbeat_at": stamp(row.heartbeat_at), "last_error": row.last_error,
        "last_status": row.last_status, "latest": ({"id": latest.id, "status": latest.status,
        "started_at": stamp(latest.started_at), "finished_at": stamp(latest.finished_at),
        "found": latest.found, "added": latest.added, "updated": latest.updated,
        "errors": latest.errors} if latest else None)}

class SearchWorker:
    def __init__(self, session_factory, refresh=None, clock=now_utc):
        self.factory, self.clock = session_factory, clock
        if refresh is None:
            from ...ingestion import run_refresh
            refresh = run_refresh
        self.refresh = refresh
        self.stop_event = threading.Event()
        self.job = None
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.run, name="grantiq-search-schedule", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)

    def tick(self):
        """Called only by the process holding scheduler.lock; never blocks on HTTP."""
        now = self.clock()
        with self.factory() as session:
            row = ensure_schedule(session, now)
            row.heartbeat_at = now
            if self.job is None and row.last_status == "running":
                # Process restart: recover one interrupted search, not every missed interval.
                row.last_status = "interrupted"
                row.next_run_at = now
            due = row.enabled and utc(row.next_run_at) <= now and not (self.job and self.job.is_alive())
            if due:
                row.last_started_at, row.last_status, row.last_error = now, "running", ""
                row.next_run_at = now + timedelta(hours=row.interval_hours)
            session.commit()
        if due:
            self.job = threading.Thread(target=self.execute, name="grantiq-recurring-search", daemon=True)
            self.job.start()

    def execute(self):
        try:
            result = self.refresh(session_factory=self.factory, max_records=int(os.getenv("GRANTIQ_MAX_RECORDS", "100")))
        except Exception as exc:
            log.exception("Scheduled search failed")
            result = {"status": "failed", "errors": [f"{type(exc).__name__}: {str(exc)[:300]}"]}
        with self.factory() as session:
            row = session.get(SearchSchedule, 1)
            row.last_finished_at = self.clock()
            row.last_status = result["status"]
            row.last_error = " · ".join(result.get("errors", []))[:2000]
            # Busy is safe: manual refresh or settings owns the shared ingestion lock.
            if result["status"] in {"busy", "failed"}:
                row.next_run_at = self.clock() + timedelta(minutes=1 if result["status"] == "busy" else 15)
            session.commit()

    def run(self):
        lock = FileLock(str(DATA_DIR / "scheduler.lock"))
        while not self.stop_event.is_set():
            try:
                with lock.acquire(timeout=0):
                    while not self.stop_event.is_set():
                        try:
                            self.tick()
                        except Exception:
                            log.exception("Scheduler tick failed; retrying in 30 seconds")
                        self.stop_event.wait(30)
                    # Retain ownership until an in-flight search completes.
                    if self.job:
                        self.job.join()
                    with self.factory() as session:
                        row = session.get(SearchSchedule, 1)
                        if row:
                            row.heartbeat_at = None
                            session.commit()
            except Timeout:
                self.stop_event.wait(30)
