"""Authorized source administration and evidence-backed human grant review."""
import json
from datetime import date, timedelta
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from filelock import FileLock, Timeout
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool
from ..config import DATA_DIR
from ..models import ApprovedSource, Grant, GrantReview
from ..security import validate_csrf
from ..services.deduplication import canonical_url
from ..services.repository import get_profile, save_assessment
from ..services.verification import REVIEW_FIELDS, source_revision, review_state, validate_facts, assess_effective
from ..sources.generic_scraper import validate_public_url
from .web import render, session_for

router = APIRouter()
SELECTOR_KEYS = {"title", "description", "eligibility", "deadline", "award_min", "award_max", "application_url", "applicant_types", "geography", "geography_scope", "populations", "categories", "programs", "grant_status"}

def evidence_link(value):
    value = str(value).strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Enter an HTTP(S) evidence URL.")
    return value

@router.get("/sources/new")
def new_source(request: Request):
    with session_for(request) as session:
        return render(request, "source_form.html", session, managed_source=None)

@router.get("/sources/{source_id}/edit")
def edit_source(request: Request, source_id: int):
    with session_for(request) as session:
        source = session.get(ApprovedSource, source_id)
        if source is None:
            raise HTTPException(404, "Source not found")
        return render(request, "source_form.html", session, managed_source=source)

@router.post("/sources/save")
async def save_source(request: Request):
    form = await request.form()
    validate_csrf(request, form)
    return await run_in_threadpool(_save_source, request, form)

def _save_source(request, form):
    try:
        name = str(form.get("name", "")).strip()
        reviewer = str(form.get("reviewed_by", "")).strip()
        if len(reviewer) > 200:
            raise ValueError("Reviewer name must be no longer than 200 characters.")
        if not name or len(name) > 200 or name.casefold() == "grants.gov":
            raise ValueError("Enter a foundation or local-source name of 1–200 characters.")
        url = canonical_url(str(form.get("url", "")).strip())
        # Saving checks public DNS only. It does not fetch the submitted page.
        validate_public_url(url)
        selectors = json.loads(str(form.get("selectors", "{}")) or "{}")
        if not isinstance(selectors, dict) or set(selectors) - SELECTOR_KEYS:
            raise ValueError("Extraction rules must be a JSON object with supported selector names.")
        import soupsieve
        for key, value in selectors.items():
            if not isinstance(value, str) or not value.strip() or len(value) > 500:
                raise ValueError("Each extraction rule must be a CSS selector of 1–500 characters.")
            try:
                soupsieve.compile(value)
            except soupsieve.SelectorSyntaxError as exc:
                raise ValueError(f"Invalid CSS selector for {key}.") from exc
        enabled = form.get("enabled") == "yes"
        terms = form.get("terms_reviewed") == "yes"
        if enabled and not terms:
            raise ValueError("Review the site's terms before enabling collection.")
        if terms and (not reviewer or len(reviewer) > 200):
            raise ValueError("Record who reviewed the source's terms.")
        reference = evidence_link(form["terms_reference"]) if form.get("terms_reference") else ""
        source_id = int(form["source_id"]) if form.get("source_id") else None
        with session_for(request) as session:
            with FileLock(str(DATA_DIR / "refresh.lock"), timeout=0):
                source = session.get(ApprovedSource, source_id) if source_id else ApprovedSource()
                if source is None:
                    raise HTTPException(404, "Source not found")
                source.name, source.url = name, url
                source.enabled, source.terms_reviewed = enabled, terms
                source.reviewed_by, source.terms_reference, source.selectors = reviewer, reference, selectors
                session.add(source)
                session.commit()
        return RedirectResponse("/sources?notice=Source+saved.+Enabled+pages+will+be+checked+on+the+next+refresh.", status_code=303)
    except Timeout:
        raise HTTPException(409, "A refresh is running. Save this source after it finishes.")
    except IntegrityError:
        raise HTTPException(409, "That page is already configured. Edit its existing source entry.")
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc))

@router.post("/sources/{source_id}/disable")
async def disable_source(request: Request, source_id: int):
    validate_csrf(request, await request.form())
    try:
        with FileLock(str(DATA_DIR / "refresh.lock"), timeout=0):
            with session_for(request) as session:
                source = session.get(ApprovedSource, source_id)
                if not source:
                    raise HTTPException(404, "Source not found")
                source.enabled = False
                session.commit()
    except Timeout:
        raise HTTPException(409, "A refresh is running. Disable this source after it finishes.")
    return RedirectResponse("/sources?notice=Source+disabled.+Existing+grant+records+are+preserved.", status_code=303)

@router.get("/grants/{grant_id}/verify")
def verification(request: Request, grant_id: int):
    with session_for(request) as session:
        grant = session.get(Grant, grant_id)
        if not grant:
            raise HTTPException(404, "Grant not found")
        state, latest = review_state(grant)
        values = {**grant.details, **(latest.facts if latest and latest.action != "withdrawn" else {})}
        return render(request, "verification.html", session, grant_id=grant.id, original=grant.details, values=values,
            review_fields=REVIEW_FIELDS, latest=latest, verification_state=state, history=grant.reviews,
            default_valid_until=date.today()+timedelta(days=30), source_revision=source_revision(grant.details))

@router.post("/grants/{grant_id}/verify")
async def save_verification(request: Request, grant_id: int):
    form = await request.form()
    validate_csrf(request, form)
    return await run_in_threadpool(_save_verification, request, grant_id, form)

def _save_verification(request, grant_id, form):
    try:
        reviewer = str(form.get("reviewed_by", "")).strip()
        note = str(form.get("evidence_note", "")).strip()
        if not reviewer or len(reviewer) > 200 or len(note) < 20 or len(note) > 15000:
            raise ValueError("Enter a reviewer name and supporting source notes of 20–15,000 characters.")
        evidence = evidence_link(form.get("evidence_url", ""))
        valid_until = date.fromisoformat(str(form.get("valid_until", "")))
        if not date.today() <= valid_until <= date.today()+timedelta(days=180):
            raise ValueError("Verification must expire between today and 180 days from today.")
        facts = {}
        for key, _, kind in REVIEW_FIELDS:
            if form.get("verify_"+key) != "yes":
                continue
            raw = str(form.get(key, "")).strip()
            if kind == "list":
                facts[key] = [v.strip() for v in raw.splitlines() if v.strip()]
            elif kind == "bool":
                if raw not in {"yes", "no", "unknown"}:
                    raise ValueError("Choose Yes, No, or Unknown for verified conditions.")
                facts[key] = {"yes": True, "no": False, "unknown": None}[raw]
            elif kind in {"number", "date", "url"}:
                facts[key] = raw or None
            else:
                facts[key] = raw
        with FileLock(str(DATA_DIR / "refresh.lock"), timeout=0):
            with session_for(request) as session:
                grant = session.get(Grant, grant_id)
                if not grant:
                    raise HTTPException(404, "Grant not found")
                revision = source_revision(grant.details)
                if form.get("source_revision") != revision:
                    raise HTTPException(409, "The source changed while this form was open. Reload and review the new source facts.")
                facts = validate_facts(grant.details, facts)
                review = GrantReview(grant=grant, facts=facts, source_revision=revision, evidence_url=evidence,
                    evidence_note=note, reviewed_by=reviewer, valid_until=valid_until, action="verified")
                session.add(review)
                session.flush()
                save_assessment(session, grant, assess_effective(grant, get_profile(session)))
                session.commit()
        return RedirectResponse(f"/grants/{grant_id}?notice=Verified+facts+saved+with+evidence.+The+score+has+been+recalculated.", status_code=303)
    except Timeout:
        raise HTTPException(409, "A refresh is running. Save the verification after it finishes.")
    except ValueError as exc:
        raise HTTPException(422, str(exc))

@router.post("/grants/{grant_id}/verify/withdraw")
async def withdraw_verification(request: Request, grant_id: int):
    form = await request.form()
    validate_csrf(request, form)
    return await run_in_threadpool(_withdraw_verification, request, grant_id, form)

def _withdraw_verification(request, grant_id, form):
    reviewer = str(form.get("reviewed_by", "")).strip()
    if not reviewer or len(reviewer) > 200:
        raise HTTPException(422, "Record who is withdrawing the verification.")
    try:
        with FileLock(str(DATA_DIR / "refresh.lock"), timeout=0):
            with session_for(request) as session:
                grant = session.get(Grant, grant_id)
                if not grant:
                    raise HTTPException(404, "Grant not found")
                session.add(GrantReview(grant=grant, facts={}, source_revision=source_revision(grant.details),
                    evidence_url=grant.details["source_url"], evidence_note="Staff withdrew the prior verified facts.",
                    reviewed_by=reviewer, valid_until=date.today(), action="withdrawn"))
                session.flush()
                save_assessment(session, grant, assess_effective(grant, get_profile(session)))
                session.commit()
    except Timeout:
        raise HTTPException(409, "A refresh is running. Withdraw the verification after it finishes.")
    return RedirectResponse(f"/grants/{grant_id}?notice=Verification+withdrawn.+The+score+now+uses+the+original+source+facts.", status_code=303)
