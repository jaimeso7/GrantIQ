from datetime import timedelta
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from ..security import validate_csrf
from ..services.irs990_schedule import ensure_irs990_schedule, irs990_status, utc
from ..services.scheduler import INTERVALS, ensure_schedule, now_utc, schedule_status
from .web import session_for

router = APIRouter()

@router.get("/api/search-schedule")
def status(request: Request):
    with session_for(request) as session:
        return schedule_status(session)

@router.post("/search-schedule")
async def save_schedule(request: Request):
    form = await request.form()
    validate_csrf(request, form)
    try:
        interval = int(form.get("interval_hours", "6"))
    except ValueError:
        raise HTTPException(422, "Choose a supported search interval.")
    if interval not in INTERVALS:
        raise HTTPException(422, "Choose 3, 6, 12, or 24 hours.")
    with session_for(request) as session:
        row = ensure_schedule(session)
        enabled = form.get("enabled") == "yes"
        if enabled and not row.enabled:
            row.next_run_at = now_utc()
        elif interval != row.interval_hours:
            row.next_run_at = now_utc() + timedelta(hours=interval)
        row.enabled, row.interval_hours = enabled, interval
        session.commit()
    return RedirectResponse("/sources?notice=Search+schedule+saved.+An+in-progress+search+will+finish+normally.", status_code=303)

@router.get("/api/irs990-schedule")
def irs990_schedule_status(request: Request):
    with session_for(request) as session:
        return irs990_status(session)

@router.post("/irs990-schedule")
async def save_irs990_schedule(request: Request):
    form = await request.form()
    validate_csrf(request, form)
    with session_for(request) as session:
        row = ensure_irs990_schedule(session)
        enabled = form.get("enabled") == "yes"
        if enabled and not row.enabled and utc(row.next_run_at) < now_utc():
            # Resuming after a long pause checks soon rather than immediately.
            row.next_run_at = now_utc() + timedelta(hours=1)
        row.enabled = enabled
        session.commit()
    return RedirectResponse("/sources?notice=990+schedule+saved.#irs990-schedule", status_code=303)

@router.post("/irs990-schedule/run")
async def run_irs990_now(request: Request):
    validate_csrf(request, await request.form())
    with session_for(request) as session:
        row = ensure_irs990_schedule(session)
        if row.last_status == "running":
            return RedirectResponse("/sources?notice=An+IRS+990+check+is+already+running.#irs990-schedule", status_code=303)
        row.next_run_at = now_utc()
        session.commit()
    return RedirectResponse("/sources?notice=IRS+990+check+queued.+It+starts+within+a+minute+while+the+app+is+running.#irs990-schedule", status_code=303)
