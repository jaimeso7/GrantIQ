from datetime import date, datetime, timezone
import yaml
from sqlalchemy import select
from sqlalchemy.orm import object_session, selectinload
from ..config import ROOT
from ..models import Organization, Grant, SourceRecord, GrantAssessment, PipelineEntry
from ..schemas import OrganizationProfile, GrantRecord, Assessment
from .deduplication import fingerprint, canonical_url
from .verification import effective_record, review_state, assess_effective

def get_profile(session) -> OrganizationProfile:
    row = session.get(Organization, 1)
    if row is None:
        path = ROOT / "config" / "organization.yaml"
        profile = OrganizationProfile(**(yaml.safe_load(path.read_text(encoding="utf-8")) or {})) if path.exists() else OrganizationProfile()
        session.add(Organization(id=1, profile=profile.model_dump(mode="json")))
        session.commit()
        return profile
    return OrganizationProfile(**row.profile)

def set_profile(session, profile):
    from .research_context import invalidate_staff_context
    invalidate_staff_context(session)
    row = session.get(Organization, 1)
    if row is None:
        row = Organization(id=1)
        session.add(row)
    row.profile = profile.model_dump(mode="json")
    row.updated_at = datetime.now(timezone.utc)
    session.flush()

def save_assessment(session, grant, assessment):
    if grant.assessment is None:
        grant.assessment = GrantAssessment()
    grant.assessment.fit_score = assessment.fit_score
    grant.assessment.confidence_score = assessment.confidence_score
    grant.assessment.eligibility_status = assessment.eligibility_status
    grant.assessment.result = assessment.model_dump(mode="json")

def upsert_grant(session, record: GrantRecord, assessment: Assessment, *, profile=None, embedder=None):
    source_url = canonical_url(record.source_url)
    source = session.scalar(select(SourceRecord).where(SourceRecord.source == record.source, SourceRecord.source_id == record.source_id))
    fp = fingerprint(record)
    grant = source.grant if source else session.scalar(select(Grant).where(Grant.fingerprint == fp))
    if grant is None:
        # URLs identify an opportunity only on the same source and matching title;
        # generic listing pages and recurring cycles must never be merged by URL alone.
        candidates = session.scalars(select(SourceRecord).where(SourceRecord.source_url == source_url, SourceRecord.source == record.source)).all()
        from .deduplication import normalized_text
        for candidate in candidates:
            g = candidate.grant
            if normalized_text(g.grant_title) == normalized_text(record.grant_title) and g.deadline == record.deadline:
                grant = g
                break
    added = grant is None
    if added:
        grant = Grant(fingerprint=fp)
        session.add(grant)
    elif grant.fingerprint != fp:
        collision = session.scalar(select(Grant).where(Grant.fingerprint == fp, Grant.id != grant.id))
        if collision:
            # Keep both staff histories intact rather than merging an ambiguous revision.
            record = record.model_copy(update={"warnings": [*record.warnings, f"Potential duplicate with grant #{collision.id}; review the revised title, funder, and deadline before merging."]})
            assessment = assessment.model_copy(update={"eligibility_status": "Needs Review" if assessment.eligibility_status != "Ineligible" else "Ineligible", "recommendation": "Needs Review" if assessment.eligibility_status != "Ineligible" else "INELIGIBLE", "warnings": [*assessment.warnings, record.warnings[-1]]})
        else:
            grant.fingerprint = fp
    for name in ("grant_title", "funder_name", "description", "eligibility_text", "award_min", "award_max", "estimated_award", "open_date", "deadline", "grant_status", "last_checked"):
        setattr(grant, name, getattr(record, name))
    # Preserve staff-owned pipeline independently of refreshed source metadata.
    grant.details = record.model_dump(mode="json")
    session.flush()
    if source is None:
        source = SourceRecord(grant=grant, source=record.source, source_id=record.source_id)
        session.add(source)
    source.source_url, source.last_checked, source.raw_text = source_url, record.last_checked, record.raw_text
    if grant.reviews:
        assessment = assess_effective(grant, profile or get_profile(session), embedder=embedder)
    if any("Potential duplicate with grant #" in warning for warning in record.warnings) and assessment.eligibility_status != "Ineligible":
        assessment.eligibility_status = assessment.recommendation = "Needs Review"
        assessment.warnings = list(dict.fromkeys([*assessment.warnings, *[w for w in record.warnings if "Potential duplicate with grant #" in w]]))
    save_assessment(session, grant, assessment)
    session.flush()
    return grant, added

def grant_view(grant):
    pipeline = None
    if grant.pipeline:
        pipeline = {c.name: getattr(grant.pipeline, c.name) for c in PipelineEntry.__table__.columns}
    record = effective_record(grant)
    assessment = Assessment(**grant.assessment.result) if grant.assessment else Assessment()
    state, review = review_state(grant)
    if state in {"expired", "source_changed"} and object_session(grant):
        assessment = assess_effective(grant, get_profile(object_session(grant)))
    # Immediate read-side override remains safe while another refresh owns the lock.
    if record.grant_status in {"closed", "archived"} or (record.deadline and record.deadline < date.today()):
        reason = "The opportunity is closed, archived, or past its application deadline."
        assessment = assessment.model_copy(update={"fit_score": 0, "eligibility_status": "Ineligible", "recommendation": "INELIGIBLE", "match_explanation": ["A passed deadline overrides all fit points."], "warnings": list(dict.fromkeys([reason, *assessment.warnings])), "components": [c.model_copy(update={"points": 0, "explanation": reason}) for c in assessment.components], "eligibility_checks": [{"key": "deadline", "outcome": "fail", "status": "fail", "explanation": reason}, *[c for c in assessment.eligibility_checks if c.get("key") != "deadline"]]})
    from .research_context import staff_context
    context = staff_context(object_session(grant), record) if object_session(grant) else None
    return dict(id=grant.id, record=record, assessment=assessment, pipeline=pipeline, date_discovered=grant.date_discovered, verification_state=state, verification=review, staff_context=context)

def rescore_all(session, profile, *, embedder=None):
    from .scoring import score_grant
    today = date.today()
    expired = 0
    grants = session.scalars(select(Grant).options(
        selectinload(Grant.reviews), selectinload(Grant.assessment),
    ))
    for grant in grants:
        record = effective_record(grant)
        if record.deadline and record.deadline < today and grant.grant_status not in {"closed", "archived"}:
            grant.grant_status = "closed"
            expired += 1
        else:
            grant.grant_status = record.grant_status
        save_assessment(session, grant, assess_effective(grant, profile, today=today, embedder=embedder))
    session.flush()
    return expired
