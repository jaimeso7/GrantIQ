"""Deterministic, explainable 100-point matching with eligibility override.

An injected embedder needs only ``similarity(profile_text, grant_text) -> float``.
The normal embedder uses local MiniLM; missing model files never masquerade as
semantic scoring. Historical evidence without a source URL earns no points.
"""

from __future__ import annotations

from datetime import date
import math
import re
from urllib.parse import urlsplit

from ..schemas.domain import Assessment, GrantRecord, OrganizationProfile, ScoreComponent
from .eligibility import contains_phrase, evaluate_eligibility, geography_alignment, normalize
from .embeddings import EmbeddingUnavailable, get_embedder

STOP_WORDS = {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "it", "of", "on", "or", "our", "that", "the", "their", "this", "to", "with", "we", "will", "through", "provide", "provides", "program", "programs", "service", "services", "support", "supports", "fund", "funding", "grant", "grants", "organization", "organizations", "nonprofit", "nonprofits"}
SYNONYMS = {
    "eye": "vision", "eyes": "vision", "ocular": "vision", "ophthalmic": "vision", "blindness": "vision",
    "healthcare": "health", "medical": "health", "healthy": "health",
    "child": "children", "kids": "children", "pediatric": "children", "paediatric": "children",
    "youth": "children", "adolescent": "children", "adolescents": "children",
    "senior": "older", "seniors": "older", "elderly": "older", "aging": "older",
    "adults": "adult", "communities": "community", "families": "family",
    "screenings": "screening", "preventative": "preventive", "prevention": "preventive",
    "disabilities": "disability", "disabled": "disability", "accessible": "accessibility",
    "students": "student", "schools": "school", "rural": "rural", "underserved": "underserved",
}
LABELS = {"mission": "Mission / subject alignment", "geography": "Geographic alignment", "population": "Population alignment", "funding": "Funding amount fit", "program": "Program / grant type fit", "past_giving": "Past giving / similar recipients", "readiness": "Deadline / application readiness"}


def _tokens(text: str) -> set[str]:
    return {SYNONYMS.get(token, token) for token in normalize(text).split() if len(token) > 2 and token not in STOP_WORDS}


def _overlap(target: str, offered: str) -> tuple[float, list[str]]:
    wanted, available = _tokens(target), _tokens(offered)
    common = sorted(wanted & available)
    # Source coverage: a specific grant need not repeat every organization interest.
    denominator = min(len(wanted), len(available))
    return (len(common) / denominator if denominator else 0.0), common


def _funding(grant: GrantRecord, profile: OrganizationProfile) -> tuple[float, str]:
    low, high, typical = grant.award_min, grant.award_max, grant.estimated_award
    if low is None and high is None and typical is None:
        return .4, "Award amount is unknown; no funding value has been invented."
    if high is not None and high < profile.minimum_desired_award:
        return 0, f"Maximum award ${high:,.0f} is below the configured minimum."
    if profile.maximum_desired_award is not None and low is not None and low > profile.maximum_desired_award:
        return 0, "The award range is above the configured maximum desired award."
    likely = typical if typical is not None else high if high is not None else low
    if likely < profile.minimum_desired_award:
        return .7, f"Estimated / reported award ${likely:,.0f} is smaller than desired; confirm available award sizes."
    if profile.maximum_desired_award is not None and likely > profile.maximum_desired_award:
        return .7, "The award range overlaps funding preferences, but its upper / estimated value exceeds the desired maximum."
    if high is not None and low is not None:
        return 1, f"Reported award range ${low:,.0f}–${high:,.0f} meets the configured funding preferences."
    return .9, f"Reported award ${likely:,.0f} meets funding preferences; the complete award range is not known."


def _past_giving(grant: GrantRecord, profile: OrganizationProfile) -> tuple[float, str]:
    evidence = []
    for item in grant.past_giving:
        source_url = item.get("source_url") or item.get("evidence_url") or ""
        parsed = urlsplit(str(source_url))
        recipient = str(item.get("recipient_name") or item.get("recipient") or "").strip()
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or not recipient:
            continue
        details = " ".join(str(item.get(key, "")) for key in ("description", "purpose", "program", "categories", "populations_served", "location", "geography"))
        alignment, common = _overlap(" ".join([profile.mission, *profile.programs, *profile.funding_interests, *profile.populations_served, *profile.service_locations]), details)
        # User-provided arbitrary 'similarity' flags/scores are deliberately ignored.
        if common:
            evidence.append((alignment, recipient, str(source_url)))
    if not evidence:
        return 0, "No source-backed historical recipient evidence with relevant giving details is available; 0 points."
    best = max(evidence, key=lambda value: value[0])
    return min(1, best[0]), f"Relevant publicly attributed giving to {best[1]}; evidence: {best[2]}. {len(evidence)} relevant recipient record(s)."


def _readiness(grant: GrantRecord, profile: OrganizationProfile, today: date) -> tuple[float, str]:
    if grant.grant_status in {"closed", "archived"} or (grant.deadline is not None and grant.deadline < today):
        return 0, "The opportunity is closed or its deadline has passed."
    if grant.grant_status == "forecasted" or (grant.open_date is not None and grant.open_date > today):
        return 0, "Applications are not yet confirmed open; monitor the future opportunity."
    if grant.deadline is None:
        if re.search(r"\b(rolling|ongoing|year round|no deadline)\b", normalize(grant.deadline_text)) and grant.grant_status == "posted":
            return .8, "Source reports an open rolling / ongoing deadline; confirm the current application cycle."
        return .2, "Deadline is unknown and needs verification."
    days = (grant.deadline - today).days
    long, medium, short = profile.readiness_thresholds
    fraction = 1 if days > long else .8 if days >= medium else .6 if days >= short else .2
    return fraction, f"{days} days remain; configured readiness thresholds are >{long}, {medium}–{long}, and {short}–{medium - 1} days."


def data_confidence(grant: GrantRecord) -> float:
    """Completeness of source facts, deliberately independent of mission similarity."""
    eligibility = 10 * bool(grant.eligibility_text.strip()) + 10 * bool(grant.applicant_types)
    geography = 15 * (bool(grant.geographic_restrictions) or grant.geography_scope == "national")
    deadline = 15 * (grant.deadline is not None or bool(re.search(r"\b(rolling|ongoing|year round|no deadline)\b", normalize(grant.deadline_text))))
    funding = 15 * any(value is not None for value in (grant.award_min, grant.award_max, grant.estimated_award))
    program = 15 * bool(grant.program_areas or grant.categories)
    application = 10 * bool(grant.application_url)
    funder = 10 * (normalize(grant.funder_name) not in {"", "unknown", "not specified"})
    return float(eligibility + geography + deadline + funding + program + application + funder)


def recommendation_label(score: float) -> str:
    for minimum, label in ((90, "Exceptional Match"), (80, "Strong Match"), (70, "Good Match"), (60, "Possible Match"), (40, "Low Priority")):
        if score >= minimum:
            return label
    return "Poor Match"


def score_grant(grant: GrantRecord, profile: OrganizationProfile, *, today: date | None = None, embedder=None) -> Assessment:
    today = today or date.today()
    eligibility = evaluate_eligibility(grant, profile, today=today)
    warnings = list(dict.fromkeys([*grant.warnings, *eligibility.warnings]))
    confidence = data_confidence(grant)
    if eligibility.status == "Ineligible":
        return Assessment(
            fit_score=0,
            confidence_score=confidence,
            eligibility_status="Ineligible",
            recommendation="INELIGIBLE",
            match_explanation=["A hard eligibility disqualifier overrides mission similarity and all recommendation points."],
            warnings=warnings,
            eligibility_checks=eligibility.checks,
            components=[ScoreComponent(key=key, label=LABELS[key], points=0, maximum=weight, explanation="Not awarded: eligibility gate failed before scoring.") for key, weight in profile.weights.items()],
            semantic_mode="not_run_ineligible",
        )

    org_text = ". ".join([profile.mission, profile.description, *profile.programs, *profile.funding_interests])
    grant_text = ". ".join([grant.grant_title, grant.description, *grant.program_areas, *grant.categories])
    keyword, common = _overlap(org_text, grant_text)
    similarity = None
    mode = "local"
    try:
        similarity = float((embedder if embedder is not None else get_embedder()).similarity(org_text, grant_text))
        if not math.isfinite(similarity):
            raise EmbeddingUnavailable("Local embedding inference returned an invalid similarity.")
        similarity = max(-1.0, min(1.0, similarity))
        mission = .65 * max(0, similarity) + .35 * keyword
        mission_explanation = f"65% local MiniLM cosine similarity ({similarity:.3f}) + 35% keyword coverage ({keyword:.0%}). Shared subjects: {', '.join(common[:12]) or 'none'}."
        if embedder is not None:
            mode = getattr(embedder, "backend_name", "injected")
    except (EmbeddingUnavailable, ImportError, OSError, RuntimeError) as exc:
        mode = "keyword_fallback"
        mission = .35 * keyword
        mission_explanation = f"Local embeddings unavailable. Keyword coverage {keyword:.0%}; only the 35% keyword portion can earn points."
        warnings.append(str(exc))

    geo = geography_alignment(grant, profile)
    if grant.populations_served and profile.populations_served:
        population, population_common = _overlap(" ".join(profile.populations_served), " ".join(grant.populations_served))
        population_explanation = "Source population overlap: " + (", ".join(population_common) if population_common else "no confirmed overlap; inspect the proposed beneficiaries") + "."
    else:
        population = .25
        population_explanation = "Population information is incomplete; only uncertainty credit is awarded."
    if grant.program_areas or grant.categories:
        program, program_common = _overlap(" ".join([*profile.programs, *profile.funding_interests]), " ".join([*grant.program_areas, *grant.categories]))
        program_explanation = "Program / funding-interest overlap: " + (", ".join(program_common) if program_common else "none confirmed") + "."
    else:
        program = .2
        program_explanation = "Program and grant-type information is missing; confirm supported uses."
    funding, funding_explanation = _funding(grant, profile)
    historical, historical_explanation = _past_giving(grant, profile)
    readiness, readiness_explanation = _readiness(grant, profile, today)
    fractions = {
        "mission": (mission, mission_explanation), "geography": (geo.fraction, geo.explanation),
        "population": (population, population_explanation), "funding": (funding, funding_explanation),
        "program": (program, program_explanation), "past_giving": (historical, historical_explanation),
        "readiness": (readiness, readiness_explanation),
    }
    components = [ScoreComponent(key=key, label=LABELS[key], points=round(max(0, min(1, fractions[key][0])) * weight, 2), maximum=weight, explanation=fractions[key][1]) for key, weight in profile.weights.items()]
    score = round(min(100, sum(component.points for component in components)), 2)
    recommendation = "Needs Review" if eligibility.status == "Needs Review" else recommendation_label(score)
    if mode == "keyword_fallback" and not any("35%" in warning for warning in warnings):
        warnings.append("Semantic matching is unavailable; keyword-only mission scoring is capped at 35% of the mission weight.")
    return Assessment(
        fit_score=score,
        confidence_score=confidence,
        eligibility_status=eligibility.status,
        recommendation=recommendation,
        match_explanation=[f"{component.label}: {component.points:g}/{component.maximum:g}. {component.explanation}" for component in components],
        warnings=list(dict.fromkeys(warnings)),
        eligibility_checks=eligibility.checks,
        components=components,
        semantic_similarity=similarity,
        semantic_mode=mode,
    )
