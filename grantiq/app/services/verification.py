"""Evidence-backed human corrections with source-change and expiry safeguards."""
import hashlib
import json
from datetime import date
from ..schemas import GrantRecord

# A reviewer confirms source facts; scores and eligibility verdicts cannot be edited.
REVIEW_FIELDS = [
    ("eligibility_text", "Eligibility requirements", "text"),
    ("applicant_types", "Eligible applicant types", "list"),
    ("geographic_restrictions", "Eligible service locations", "list"),
    ("geography_scope", "Geographic scope", "scope"),
    ("populations_served", "Populations supported", "list"),
    ("categories", "Funding categories", "list"),
    ("program_areas", "Supported programs", "list"),
    ("award_min", "Minimum award ($)", "number"),
    ("award_max", "Maximum award ($)", "number"),
    ("estimated_award", "Typical award confirmed by source ($)", "number"),
    ("deadline", "Application deadline", "date"),
    ("deadline_text", "Deadline notes", "text"),
    ("grant_status", "Application status", "status"),
    ("application_url", "Direct application URL", "url"),
    ("application_requirements", "Required application materials", "list"),
    ("contact_information", "Application contact", "text"),
    ("loi_required", "Letter of inquiry required", "bool"),
    ("invitation_only", "Invitation required", "bool"),
    ("matching_funds_required", "Matching funds required", "bool"),
    ("fiscal_sponsor_required", "Fiscal sponsor required", "bool"),
    ("existing_relationship_required", "Existing funder relationship required", "bool"),
    ("budget_min", "Minimum organization budget ($)", "number"),
    ("budget_max", "Maximum organization budget ($)", "number"),
]
ALLOWED_REVIEW_FIELDS = {row[0] for row in REVIEW_FIELDS}

def source_revision(details):
    # A mere recheck does not invalidate evidence. Changes in source facts do.
    content = {k: v for k, v in details.items() if k not in {"last_checked", "warnings"}}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def review_state(grant, today=None):
    today = today or date.today()
    if not grant.reviews:
        return "none", None
    latest = max(grant.reviews, key=lambda row: row.id or 0)
    if latest.action == "withdrawn":
        return "withdrawn", latest
    if latest.source_revision != source_revision(grant.details):
        return "source_changed", latest
    if latest.valid_until < today:
        return "expired", latest
    return "current", latest

def effective_record(grant, today=None):
    original = GrantRecord(**grant.details)
    state, review = review_state(grant, today)
    if state == "current":
        record = GrantRecord(**{**grant.details, **review.facts})
        record.warnings = [f"Original import: {warning}" for warning in original.warnings]
        record.warnings.append(f"Includes facts verified by {review.reviewed_by}; evidence: {review.evidence_url}. Review expires {review.valid_until}.")
        original = record
    elif state in {"expired", "source_changed"}:
        original.warnings.append("Staff verification needs renewal: " + ("the source facts changed." if state == "source_changed" else "the verification period expired."))
    if original.deadline and original.deadline < (today or date.today()) and original.grant_status != "archived":
        original.grant_status = "closed"
    return original

def assess_effective(grant, profile, *, embedder=None, today=None):
    from .scoring import score_grant
    record = effective_record(grant, today)
    assessment = score_grant(record, profile, embedder=embedder, today=today)
    state, _ = review_state(grant, today)
    if state in {"expired", "source_changed"} and assessment.eligibility_status != "Ineligible":
        assessment.eligibility_status = "Needs Review"
        assessment.recommendation = "Needs Review"
    return assessment

def validate_facts(original, facts):
    if not facts or set(facts) - ALLOWED_REVIEW_FIELDS:
        raise ValueError("Select at least one supported source fact to verify.")
    record = GrantRecord(**{**original, **facts})
    if any(record.model_dump()[key] is not None and record.model_dump()[key] < 0 for key in ("budget_min", "budget_max")):
        raise ValueError("Organization budget limits must be nonnegative.")
    if record.budget_min is not None and record.budget_max is not None and record.budget_min > record.budget_max:
        raise ValueError("Minimum organization budget exceeds maximum.")
    normalized = record.model_dump(mode="json")
    return {key: normalized[key] for key in facts}
