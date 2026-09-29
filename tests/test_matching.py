"""Core safety and score invariants; normal tests need no model or network."""

from datetime import date, timedelta
import os

import pytest

from grantiq.app.schemas.domain import DEFAULT_WEIGHTS, GrantRecord, OrganizationProfile
from grantiq.app.services.eligibility import evaluate_eligibility, geography_alignment
from grantiq.app.services.embeddings import EmbeddingUnavailable, LocalEmbedder
from grantiq.app.services.scoring import score_grant

TODAY = date(2026, 9, 14)


class FixedEmbedder:
    backend_name = "deterministic_test"

    def __init__(self, value=.95):
        self.value = value
        self.calls = 0

    def similarity(self, first, second):
        assert isinstance(first, str) and isinstance(second, str)
        self.calls += 1
        return self.value


class MissingEmbedder:
    def similarity(self, first, second):
        raise EmbeddingUnavailable("Local MiniLM is not cached.")


@pytest.fixture
def profile():
    return OrganizationProfile(
        mission="Provide community vision care, eye screenings, and preventive health access.",
        description="Vision services for underserved children and adults.",
        service_locations=["Duval County, Florida", "Clay County, FL", "Nassau County, Florida"],
        populations_served=["children", "adults", "underserved communities"],
        programs=["vision screening", "eye care", "preventive healthcare"],
        funding_interests=["vision care", "eye health", "preventive healthcare", "community health"],
        annual_budget=1_000_000,
    )


@pytest.fixture
def grant():
    return GrantRecord(
        source="fixture", source_id="excellent", source_url="https://example.org/vision-grant",
        application_url="https://example.org/apply", funder_name="Fixture Health Foundation",
        grant_title="Community Vision Care", description="Preventive eye health and community vision screening for underserved children and adults.",
        eligibility_text="Registered 501(c)(3) nonprofit organizations are eligible. Supports preventive vision services.",
        applicant_types=["501(c)(3) nonprofits"], geographic_restrictions=["Florida"], geography_scope="state",
        populations_served=["children", "adults", "underserved communities"],
        program_areas=["vision care", "eye screening", "preventive healthcare"], categories=["health"],
        award_min=10_000, award_max=50_000, deadline=TODAY + timedelta(days=60), grant_status="posted",
        invitation_only=False, matching_funds_required=False, fiscal_sponsor_required=False, existing_relationship_required=False,
    )


def test_excellent_match_has_explainable_components(profile, grant):
    assessment = score_grant(grant, profile, today=TODAY, embedder=FixedEmbedder())
    assert assessment.eligibility_status == "Eligible"
    assert assessment.fit_score >= 80
    assert assessment.recommendation == "Strong Match"
    assert assessment.confidence_score == 100
    assert sum(component.points for component in assessment.components) == pytest.approx(assessment.fit_score)
    assert {component.key for component in assessment.components} == set(DEFAULT_WEIGHTS)
    assert all(component.explanation for component in assessment.components)
    assert len(assessment.match_explanation) == 7


@pytest.mark.parametrize("updates", [
    {"geographic_restrictions": ["California"]},
    {"deadline": TODAY - timedelta(days=1)},
    {"grant_status": "archived"},
    {"grant_status": "closed"},
    {"award_max": 4_999, "award_min": 1_000},
    {"applicant_types": ["State governments", "County governments"]},
    {"applicant_types": ["Public and State controlled institutions of higher education", "Private institutions of higher education"]},
    {"eligibility_text": "This program is for government applicants only."},
    {"eligibility_text": "Eligible 501(c)(3) entities may be partners. Universities only may apply."},
    {"eligibility_text": "501(c)(3) nonprofit organizations are not eligible."},
    {"eligibility_text": "This opportunity excludes nonprofits."},
    {"budget_max": 500_000},
    {"budget_min": 2_000_000},
])
def test_hard_disqualifier_precedes_semantics(profile, grant, updates):
    model = FixedEmbedder(1)
    assessment = score_grant(grant.model_copy(update=updates), profile, today=TODAY, embedder=model)
    assert assessment.eligibility_status == "Ineligible", assessment.eligibility_checks
    assert assessment.fit_score == 0
    assert assessment.recommendation == "INELIGIBLE"
    assert model.calls == 0
    assert all(component.points == 0 for component in assessment.components)


@pytest.mark.parametrize("restrictions, scope, expected, fraction", [
    (["FL"], "state", "pass", .85),
    (["Florida"], "state", "pass", .85),
    (["State of Florida"], "state", "pass", .85),
    (["United States"], "national", "pass", .5),
    (["Duval County, Florida"], "local", "pass", 1),
    (["Clay County, FL"], "local", "pass", 1),
    (["St. Johns County, Florida"], "local", "fail", 0),
    (["Orange County, California"], "local", "fail", 0),
    (["Nassau County, New York"], "local", "fail", 0),
    (["California"], "state", "fail", 0),
    (["Northeast Florida"], "regional", "review", .25),
    ([], "unknown", "review", .25),
])
def test_geography_uses_county_identity_not_just_shared_state(profile, grant, restrictions, scope, expected, fraction):
    result = geography_alignment(grant.model_copy(update={"geographic_restrictions": restrictions, "geography_scope": scope}), profile)
    assert result.outcome == expected, result.explanation
    assert result.fraction == fraction


def test_saint_county_alias(profile, grant):
    p = profile.model_copy(update={"service_locations": ["Saint Johns County, Florida"]})
    g = grant.model_copy(update={"geographic_restrictions": ["St. Johns County, FL"], "geography_scope": "local"})
    assert geography_alignment(g, p).outcome == "pass"


def test_incidental_california_program_and_population_terms_do_not_disqualify(profile, grant):
    g = grant.model_copy(update={"description": "Research from California shows older adults benefit from vision screenings.", "populations_served": ["older adults"], "program_areas": ["research"]})
    assert evaluate_eligibility(g, profile, today=TODAY).status != "Ineligible"


def test_national_exclusion_overrides_broad_scope(profile, grant):
    g = grant.model_copy(update={"geography_scope": "national", "geographic_restrictions": ["United States"], "eligibility_text": "Nonprofits are eligible, excluding Florida."})
    assert evaluate_eligibility(g, profile, today=TODAY).status == "Ineligible"


def test_textual_explicit_geography_exclusion(profile, grant):
    g = grant.model_copy(update={"geographic_restrictions": [], "geography_scope": "unknown", "eligibility_text": "Applicants must be California organizations only."})
    assert evaluate_eligibility(g, profile, today=TODAY).status == "Ineligible"


def test_nonprofit_higher_education_exception_is_not_university_only(profile, grant):
    g = grant.model_copy(update={"applicant_types": ["Nonprofits having a 501(c)(3) status with the IRS, other than institutions of higher education"]})
    assert evaluate_eligibility(g, profile, today=TODAY).status == "Eligible"


@pytest.mark.parametrize("updates", [
    {"eligibility_text": ""},
    {"applicant_types": [], "eligibility_text": "See official guidelines."},
    {"geographic_restrictions": [], "geography_scope": "unknown"},
    {"deadline": None},
    {"grant_status": "forecasted"},
    {"open_date": TODAY + timedelta(days=5)},
    {"invitation_only": True},
    {"matching_funds_required": True},
    {"fiscal_sponsor_required": True},
    {"existing_relationship_required": True},
    {"eligibility_text": "Nonprofits can apply. Matching funds are required."},
    {"eligibility_text": "Nonprofits can apply. Organizations must serve children exclusively."},
    {"award_min": None, "award_max": None},
])
def test_unknown_or_unconfirmed_eligibility_requires_review(profile, grant, updates):
    result = score_grant(grant.model_copy(update=updates), profile, today=TODAY, embedder=FixedEmbedder(1))
    assert result.eligibility_status == "Needs Review", result.eligibility_checks
    assert result.recommendation == "Needs Review"
    assert result.warnings


@pytest.mark.parametrize("flag, profile_field", [("matching_funds_required", "matching_funds_available"), ("fiscal_sponsor_required", "has_fiscal_sponsor")])
def test_explicitly_unavailable_required_resource_disqualifies(profile, grant, flag, profile_field):
    p = profile.model_copy(update={profile_field: False})
    g = grant.model_copy(update={flag: True})
    assert evaluate_eligibility(g, p, today=TODAY).status == "Ineligible"
    p = p.model_copy(update={profile_field: True})
    assert evaluate_eligibility(g, p, today=TODAY).status == "Eligible"


def test_invitation_record_resolves_review(profile, grant):
    g = grant.model_copy(update={"invitation_only": True})
    p = profile.model_copy(update={"invited_by_funders": [g.funder_name]})
    assert evaluate_eligibility(g, p, today=TODAY).status == "Eligible"


def test_missing_budget_does_not_pass_budget_gate(profile, grant):
    p = profile.model_copy(update={"annual_budget": None})
    assert evaluate_eligibility(grant.model_copy(update={"budget_min": 100_000}), p, today=TODAY).status == "Needs Review"


def test_weak_mission_has_lower_score(profile, grant):
    strong = score_grant(grant, profile, today=TODAY, embedder=FixedEmbedder(.95))
    weak = score_grant(grant.model_copy(update={"grant_title": "Marine Engineering", "description": "Autonomous underwater propulsion systems", "program_areas": ["ocean engineering"], "categories": ["technology"]}), profile, today=TODAY, embedder=FixedEmbedder(.05))
    assert weak.fit_score < strong.fit_score - 25


def test_missing_model_is_explicit_and_mission_points_capped(profile, grant):
    result = score_grant(grant, profile, today=TODAY, embedder=MissingEmbedder())
    assert result.semantic_mode == "keyword_fallback"
    assert result.semantic_similarity is None
    assert next(c for c in result.components if c.key == "mission").points <= profile.weights["mission"] * .35
    assert any("35%" in warning for warning in result.warnings)


def test_weights_are_configurable_and_score_still_sums(profile, grant):
    weights = dict(mission=40, geography=20, population=10, funding=10, program=10, past_giving=5, readiness=5)
    result = score_grant(grant, profile.model_copy(update={"weights": weights}), today=TODAY, embedder=FixedEmbedder())
    assert {c.key: c.maximum for c in result.components} == weights
    assert result.fit_score == pytest.approx(sum(c.points for c in result.components))


@pytest.mark.parametrize("days, points", [(46, 5), (45, 4), (30, 4), (29, 3), (15, 3), (14, 1), (0, 1)])
def test_deadline_readiness_boundaries(profile, grant, days, points):
    result = score_grant(grant.model_copy(update={"deadline": TODAY + timedelta(days=days)}), profile, today=TODAY, embedder=FixedEmbedder())
    assert next(c for c in result.components if c.key == "readiness").points == points


def test_custom_readiness_thresholds(profile, grant):
    p = profile.model_copy(update={"readiness_thresholds": [90, 60, 30]})
    result = score_grant(grant, p, today=TODAY, embedder=FixedEmbedder())
    assert next(c for c in result.components if c.key == "readiness").points == 4


def test_missing_history_is_zero_and_claim_alone_is_not_evidence(profile, grant):
    for history in ([], [{"recipient": "Example Health", "description": "vision care", "similarity": 1}], [{"source_url": "https://example.org/990", "similarity": 1}]):
        result = score_grant(grant.model_copy(update={"past_giving": history}), profile, today=TODAY, embedder=FixedEmbedder())
        assert next(c for c in result.components if c.key == "past_giving").points == 0


def test_source_backed_historical_giving_gets_explanation(profile, grant):
    g = grant.model_copy(update={"past_giving": [{"recipient": "Example Vision Nonprofit", "source_url": "https://example.org/990", "purpose": "community vision care eye screening"}]})
    result = score_grant(g, profile, today=TODAY, embedder=FixedEmbedder())
    component = next(c for c in result.components if c.key == "past_giving")
    assert component.points > 0
    assert "https://example.org/990" in component.explanation


def test_confidence_is_separate_from_semantics(profile, grant):
    low = score_grant(grant, profile, today=TODAY, embedder=FixedEmbedder(.01))
    high = score_grant(grant, profile, today=TODAY, embedder=FixedEmbedder(.99))
    assert low.confidence_score == high.confidence_score == 100
    incomplete = score_grant(grant.model_copy(update={"application_url": None, "eligibility_text": "", "deadline": None}), profile, today=TODAY, embedder=FixedEmbedder(.99))
    assert incomplete.confidence_score < high.confidence_score
    assert incomplete.eligibility_status == "Needs Review"


@pytest.mark.skipif(os.getenv("GRANTIQ_TEST_LOCAL_MODEL") != "1", reason="Opt-in local model test; run the download CLI first")
def test_actual_local_model_semantic_similarity():
    embedder = LocalEmbedder()
    related = embedder.similarity("Free vision screenings and eye care for children", "Pediatric eye health and prevention of blindness")
    unrelated = embedder.similarity("Free vision screenings and eye care for children", "Advanced marine propulsion and industrial metallurgy")
    identical = embedder.similarity("Local vision care", "Local vision care")
    assert related > unrelated + .2
    assert identical > .99
    assert embedder.status()["loaded"] is True
