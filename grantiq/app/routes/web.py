import csv
import hmac
import io
import os
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
import yaml
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from filelock import FileLock, Timeout
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool
from ..config import ROOT, DATA_DIR
from ..models import Grant, PipelineEntry, PIPELINE_STATUSES, RefreshRun, ApprovedSource
from ..schemas import OrganizationProfile, GrantRecord, Assessment, DEFAULT_WEIGHTS
from ..security import csrf_token, validate_csrf, check_login_limit
from ..services.repository import get_profile, set_profile, grant_view, rescore_all

router = APIRouter()
templates = Jinja2Templates(directory=str(ROOT / "grantiq" / "app" / "templates"))

def date_value(value):
    if isinstance(value, (date, datetime)):
        return value
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return None

templates.env.filters.update(
    money=lambda value: f"${value:,.0f}" if value is not None else "Unknown",
    datefmt=lambda value: date_value(value).strftime("%b %d, %Y") if date_value(value) else "Unknown",
    datetimefmt=lambda value: date_value(value).strftime("%b %d, %Y · %H:%M UTC") if date_value(value) else "Unknown",
    score=lambda value: f"{float(value):.2f}".rstrip("0").rstrip("."),
)

def render(request, template, session, **context):
    from ..services.scheduler import schedule_status
    context = {"request": request, "profile": get_profile(session), "csrf_token": csrf_token(request),
               "search_schedule": schedule_status(session),
               "authenticated": bool(request.session.get("authenticated")) or not request.app.state.password,
               "auth_enabled": bool(request.app.state.password), "page": template.split(".")[0],
               "notice": request.query_params.get("notice"), **context}
    return templates.TemplateResponse(request=request, name=template, context=context)

def session_for(request):
    return request.app.state.session_factory()

def run_dict(run):
    return {c.name: getattr(run, c.name) for c in RefreshRun.__table__.columns} if run else None

def all_grants(session):
    return [grant_view(g) for g in session.scalars(select(Grant).options(selectinload(Grant.assessment), selectinload(Grant.pipeline), selectinload(Grant.reviews))).all()]

def active(item):
    r = item["record"]
    return r.grant_status not in {"closed", "archived"} and (r.deadline is None or r.deadline >= date.today())

def filter_grants(grants, filters):
    try:
        min_score = float(filters.get("min_score") or 0)
        min_amount = float(filters.get("amount_min") or 0)
        deadline_filter = filters.get("deadline") or ""
        days = int(deadline_filter) if deadline_filter in {"7", "14", "30", "60", "90"} else None
        deadline = date.today() + timedelta(days=days) if days is not None else date.fromisoformat(deadline_filter) if deadline_filter else None
    except ValueError:
        raise HTTPException(422, "Enter a valid score, funding amount, and deadline.")
    result = []
    for item in grants:
        r, a, p = item["record"], item["assessment"], item["pipeline"]
        if item.get("staff_context") and item["staff_context"]["hidden"] and not filters.get("include_staff_hidden"):
            continue
        if not filters.get("include_closed") and not active(item):
            continue
        if a.fit_score < min_score:
            continue
        if min_amount and (max([v for v in (r.award_min, r.award_max, r.estimated_award) if v is not None], default=-1) < min_amount):
            continue
        if deadline and (not r.deadline or not date.today() <= r.deadline <= deadline):
            continue
        haystack = " ".join([r.grant_title, r.funder_name, r.description, *r.categories, *r.program_areas, *r.populations_served, *r.geographic_restrictions]).casefold()
        if any(term not in haystack for term in re.findall(r"\w+", filters.get("q", "").casefold())):
            continue
        values = {"funder": r.funder_name, "geography": " ".join(r.geographic_restrictions), "population": " ".join(r.populations_served), "category": " ".join(r.categories), "source": r.source, "eligibility": a.eligibility_status, "pipeline_status": p["status"] if p else "Discovered"}
        if any(filters.get(k) and filters[k].casefold() not in v.casefold() for k, v in values.items() if k not in {"eligibility", "pipeline_status"}):
            continue
        if any(filters.get(k) and filters[k] != values[k] for k in ("eligibility", "pipeline_status")):
            continue
        result.append(item)
    return sorted(result, key=lambda g: (-g["assessment"].fit_score, g["record"].deadline or date.max, g["record"].grant_title.casefold()))

def fresh_scores(session):
    today = date.today()
    records = session.scalars(select(Grant)).all()
    if any(not g.assessment or Assessment(**g.assessment.result).scored_at.astimezone().date() < today for g in records):
        try:
            with FileLock(str(DATA_DIR / "refresh.lock"), timeout=0):
                rescore_all(session, get_profile(session))
                session.commit()
        except Timeout:
            pass

@router.get("/")
def dashboard(request: Request):
    with session_for(request) as session:
        fresh_scores(session)
        grants = all_grants(session)
        active_grants = [g for g in grants if active(g)]
        today = date.today()
        stats = {"active": len(active_grants), "strong": sum(g["assessment"].fit_score >= 80 and g["assessment"].eligibility_status in {"Eligible", "Likely Eligible"} and g["record"].grant_status == "posted" and not (g.get("staff_context") and g["staff_context"]["hidden"]) for g in active_grants), "upcoming": sum(g["record"].deadline is not None and today <= g["record"].deadline <= today+timedelta(days=30) for g in active_grants), "new": sum(g["date_discovered"].date() >= today-timedelta(days=7) for g in active_grants)}
        options = {"categories": sorted({v for g in grants for v in g["record"].categories}), "populations": sorted({v for g in grants for v in g["record"].populations_served}), "geographies": sorted({v for g in grants for v in g["record"].geographic_restrictions}), "sources": sorted({g["record"].source for g in grants}), "funders": sorted({g["record"].funder_name for g in grants})}
        refresh = session.scalar(select(RefreshRun).order_by(RefreshRun.id.desc()).limit(1))
        modes = {g["assessment"].semantic_mode for g in grants}
        return render(request, "dashboard.html", session, grants=filter_grants(grants, dict(request.query_params)), stats=stats, filters=dict(request.query_params), options=options, refresh=run_dict(refresh), semantic_mode=", ".join(sorted(modes)) or "Not scored yet", staff_hidden_count=sum(bool(g.get("staff_context") and g["staff_context"]["hidden"]) for g in active_grants))

@router.get("/grants/{grant_id}")
def detail(request: Request, grant_id: int):
    with session_for(request) as session:
        fresh_scores(session)
        grant = session.get(Grant, grant_id)
        if grant is None:
            raise HTTPException(404, "Grant not found")
        return render(request, "detail.html", session, grant=grant_view(grant), statuses=PIPELINE_STATUSES)

@router.get("/pipeline")
def pipeline(request: Request):
    with session_for(request) as session:
        fresh_scores(session)
        grants = [g for g in all_grants(session) if g["pipeline"]]
        return render(request, "pipeline.html", session, grants=grants, statuses=PIPELINE_STATUSES)

@router.post("/grants/{grant_id}/pipeline")
async def update_pipeline(request: Request, grant_id: int):
    form = await request.form()
    validate_csrf(request, form)
    if form.get("status") not in PIPELINE_STATUSES:
        raise HTTPException(422, "Invalid pipeline status")
    try:
        amount = float(form["requested_amount"]) if form.get("requested_amount") else None
        if amount is not None and (amount < 0 or not __import__("math").isfinite(amount)):
            raise ValueError()
        application_deadline = date.fromisoformat(form["application_deadline"]) if form.get("application_deadline") else None
        submission_date = date.fromisoformat(form["submission_date"]) if form.get("submission_date") else None
    except ValueError:
        raise HTTPException(422, "Use valid dates and a nonnegative requested amount.")
    with session_for(request) as session:
        grant = session.get(Grant, grant_id)
        if grant is None:
            raise HTTPException(404, "Grant not found")
        if not grant.pipeline:
            grant.pipeline = PipelineEntry()
        for key, limit in (("notes", 20000), ("assigned_to", 200), ("final_result", 10000)):
            setattr(grant.pipeline, key, str(form.get(key, ""))[:limit])
        grant.pipeline.status = form["status"]
        grant.pipeline.requested_amount, grant.pipeline.application_deadline, grant.pipeline.submission_date = amount, application_deadline, submission_date
        session.commit()
    return RedirectResponse(f"/grants/{grant_id}?notice=Pipeline+saved", status_code=303)

@router.get("/settings")
def settings(request: Request):
    with session_for(request) as session:
        return render(request, "settings.html", session)

@router.post("/settings")
async def update_settings(request: Request):
    form = await request.form()
    validate_csrf(request, form)
    return await run_in_threadpool(save_settings, request, form)

def save_settings(request, form):
    with session_for(request) as session:
        values = get_profile(session).model_dump()
        for name in ("name", "organization_type", "mission", "description", "ein", "profile_source_url"):
            if name in form:
                values[name] = str(form[name]).strip()[:20000] or (None if name == "profile_source_url" else "")
        for name in ("service_locations", "populations_served", "programs", "funding_interests", "invited_by_funders", "existing_funder_relationships", "excluded_funders"):
            if name in form:
                # Newline delimiter preserves geographic strings such as Jacksonville, Florida.
                values[name] = [v.strip() for v in str(form[name]).splitlines() if v.strip()]
        for name in ("minimum_desired_award", "maximum_desired_award", "annual_budget", "minimum_days_to_apply"):
            if name in form:
                values[name] = form[name] or None
        for name in ("matching_funds_available", "has_fiscal_sponsor"):
            if name in form:
                values[name] = {"yes": True, "no": False, "unknown": None, "": None}.get(form[name])
        try:
            values["weights"] = {k: float(form.get("weight_"+k, values["weights"][k])) for k in DEFAULT_WEIGHTS}
            if "readiness_thresholds" in form:
                values["readiness_thresholds"] = [int(x.strip()) for x in form["readiness_thresholds"].split(",")]
            profile = OrganizationProfile(**values)
            with FileLock(str(DATA_DIR / "refresh.lock"), timeout=0):
                set_profile(session, profile)
                # Scores and eligibility update in the same transaction as the profile.
                rescore_all(session, profile)
                session.commit()
        except Timeout:
            raise HTTPException(409, "A refresh is running. Save settings after it finishes.")
        except (ValidationError, ValueError) as exc:
            session.rollback()
            response = render(request, "settings.html", session, notice=f"Settings were not saved: {str(exc)[:600]}")
            response.status_code = 422
            return response
    return RedirectResponse("/settings?notice=Settings+saved+and+grants+rescored", status_code=303)

@router.get("/sources")
def sources(request: Request):
    with session_for(request) as session:
        path = ROOT / "config" / "sources.yaml"
        config = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else []
        if isinstance(config, dict):
            config = config.get("sources", [])
        from ..services.research_context import keyword_plan
        from ..models import SearchCursor
        cursor = session.get(SearchCursor, 1)
        next_terms, _, _ = keyword_plan(get_profile(session), cursor.position if cursor else 0)
        config = [{"name": "Grants.gov", "type": "Official public API", "url": "https://www.grants.gov", "enabled": True, "description": "Public posted and forecasted federal opportunities. A record cap limits each refresh; see activity for incomplete coverage.", "keywords": next_terms}, *(config or [])]
        runs = [run_dict(r) for r in session.scalars(select(RefreshRun).order_by(RefreshRun.id.desc()).limit(30))]
        return render(request, "sources.html", session, source_configs=config or [], runs=runs, managed_sources=session.scalars(select(ApprovedSource).order_by(ApprovedSource.name)).all())

@router.post("/refresh")
async def refresh(request: Request, background_tasks: BackgroundTasks):
    form = await request.form()
    validate_csrf(request, form)
    from ...ingestion import run_refresh
    background_tasks.add_task(run_refresh, session_factory=request.app.state.session_factory, max_records=int(os.getenv("GRANTIQ_MAX_RECORDS", "100")))
    return RedirectResponse("/?notice=Refresh+started.+See+Sources+for+progress+and+errors.", status_code=303)

@router.get("/api/refresh-status")
def refresh_status(request: Request):
    with session_for(request) as session:
        return run_dict(session.scalar(select(RefreshRun).order_by(RefreshRun.id.desc()).limit(1))) or {"status": "never"}

def csv_safe(value):
    text = str(value) if value is not None else "Unknown"
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        text = "'" + text
    return text

@router.get("/export.csv")
def export(request: Request):
    with session_for(request) as session:
        fresh_scores(session)
        grants = filter_grants(all_grants(session), dict(request.query_params))
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Grant", "Funder", "Fit score", "Eligibility", "Confidence", "Recommendation", "Minimum award", "Maximum award", "Estimated award", "Deadline", "Geography", "Population", "Categories", "Why it matches", "Concerns", "Requirements", "Source", "Official URL", "Application URL", "Last checked", "Pipeline status", "Assigned to", "Requested amount", "Staff deadline", "Submission date", "Notes", "Final result", "Demo record", "Staff decision", "Staff decision reason"])
    for g in grants:
        r, a, p = g["record"], g["assessment"], g["pipeline"] or {}
        writer.writerow([csv_safe(v) for v in [r.grant_title, r.funder_name, a.fit_score, a.eligibility_status, a.confidence_score, a.recommendation, r.award_min, r.award_max, r.estimated_award, r.deadline, "; ".join(r.geographic_restrictions), "; ".join(r.populations_served), "; ".join(r.categories), "; ".join(a.match_explanation), "; ".join(a.warnings), "; ".join(r.application_requirements), r.source, r.source_url, r.application_url, r.last_checked, p.get("status", "Discovered"), p.get("assigned_to"), p.get("requested_amount"), p.get("application_deadline"), p.get("submission_date"), p.get("notes"), p.get("final_result"), r.is_demo, (g.get("staff_context") or {}).get("label", ""), (g.get("staff_context") or {}).get("reason", "")]])
    return Response("\ufeff"+output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="grantiq-opportunities.csv"'})

@router.get("/login")
def login(request: Request):
    with session_for(request) as session:
        return render(request, "login.html", session)

@router.post("/login")
async def sign_in(request: Request):
    form = await request.form()
    validate_csrf(request, form)
    check_login_limit(request)
    password = request.app.state.password
    if not password or not hmac.compare_digest(str(form.get("password", "")), password):
        with session_for(request) as session:
            response = render(request, "login.html", session, notice="The password was not recognized.")
            response.status_code = 401
            return response
    request.session.clear()
    request.session["authenticated"] = True
    csrf_token(request)
    return RedirectResponse("/", status_code=303)

@router.post("/logout")
async def sign_out(request: Request):
    validate_csrf(request, await request.form())
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
