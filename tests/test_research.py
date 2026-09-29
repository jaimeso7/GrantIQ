from datetime import date, timedelta
import re
import pytest
from sqlalchemy import select
from test_app import factory, client, record, seed, csrf, FixedEmbedder
from grantiq.app.models import Grant, GrantReview, ApprovedSource
from grantiq.app.services.verification import effective_record, review_state, source_revision, validate_facts, assess_effective
from grantiq.app.services.repository import get_profile, upsert_grant
from grantiq.app.services.scoring import score_grant
from grantiq.app.sources.generic_scraper import GenericScraperSource

@pytest.fixture(autouse=True)
def local_only_test_scoring(monkeypatch):
    monkeypatch.setattr("grantiq.app.services.scoring.get_embedder", lambda: FixedEmbedder())

def review_form(client, gid, **facts):
    response = client.get(f"/grants/{gid}/verify")
    assert response.status_code == 200, response.text
    token = re.search(r'name="csrf_token"\s+value="([^"]+)"', response.text).group(1)
    revision = re.search(r'name="source_revision"\s+value="([^"]+)"', response.text).group(1)
    return {"csrf_token": token, "source_revision": revision, "reviewed_by": "Test Researcher", "evidence_url": "https://example.org/announcement",
        "evidence_note": "Section 2 of the official announcement confirms each selected requirement.", "valid_until": str(date.today()+timedelta(days=30)), **facts}

def test_verification_changes_score_without_overwriting_source(client, factory, record):
    gid = seed(factory, record)
    form = review_form(client, gid, verify_geographic_restrictions="yes", geographic_restrictions="California")
    response = client.post(f"/grants/{gid}/verify", data=form)
    assert response.status_code == 200, response.text
    with factory() as session:
        grant = session.get(Grant, gid)
        assert grant.details["geographic_restrictions"] == ["Florida"]
        assert effective_record(grant).geographic_restrictions == ["California"]
        assert grant.assessment.fit_score == 0
        assert grant.assessment.eligibility_status == "Ineligible"
        assert len(grant.reviews) == 1
    assert "Test Researcher" in client.get(f"/grants/{gid}").text

def test_verification_survives_recheck_but_invalidates_source_change(client, factory, record):
    gid = seed(factory, record)
    form = review_form(client, gid, verify_geographic_restrictions="yes", geographic_restrictions="California")
    client.post(f"/grants/{gid}/verify", data=form)
    with factory() as session:
        rechecked = record.model_copy(update={"last_checked": record.last_checked+timedelta(hours=1)})
        profile = get_profile(session)
        grant, _ = upsert_grant(session, rechecked, score_grant(rechecked, profile), profile=profile)
        session.commit()
        assert review_state(grant)[0] == "current"
        assert grant.assessment.eligibility_status == "Ineligible"
        changed = record.model_copy(update={"description": "Updated program priorities in new source revision."})
        grant, _ = upsert_grant(session, changed, score_grant(changed, profile), profile=profile)
        session.commit()
        assert review_state(grant)[0] == "source_changed"
        assert effective_record(grant).geographic_restrictions == ["Florida"]
        assert grant.assessment.eligibility_status == "Needs Review"

def test_expired_verification_stops_overriding(client, factory, record):
    gid = seed(factory, record)
    form = review_form(client, gid, verify_geographic_restrictions="yes", geographic_restrictions="California")
    client.post(f"/grants/{gid}/verify", data=form)
    with factory() as session:
        grant = session.get(Grant, gid)
        future = date.today()+timedelta(days=31)
        assert review_state(grant, future)[0] == "expired"
        assert effective_record(grant, future).geographic_restrictions == ["Florida"]
        assert assess_effective(grant, get_profile(session), today=future).eligibility_status == "Needs Review"

def test_withdraw_preserves_review_history(client, factory, record):
    gid = seed(factory, record)
    form = review_form(client, gid, verify_geographic_restrictions="yes", geographic_restrictions="California")
    client.post(f"/grants/{gid}/verify", data=form)
    response = client.post(f"/grants/{gid}/verify/withdraw", data={"csrf_token": form["csrf_token"], "reviewed_by": "Second reviewer"})
    assert response.status_code == 200
    with factory() as session:
        grant = session.get(Grant, gid)
        assert review_state(grant)[0] == "withdrawn"
        assert len(grant.reviews) == 2
        assert effective_record(grant).geographic_restrictions == ["Florida"]

@pytest.mark.parametrize("change", [{"evidence_url":"javascript:alert(1)"}, {"evidence_note":"none"}, {"reviewed_by":""}, {"valid_until": "2099-01-01"}, {"award_min":"100000", "award_max":"1000", "verify_award_min":"yes", "verify_award_max":"yes"}])
def test_invalid_evidence_is_rejected(client, factory, record, change):
    gid = seed(factory, record)
    form = review_form(client, gid, verify_geographic_restrictions="yes", geographic_restrictions="Florida")
    assert client.post(f"/grants/{gid}/verify", data={**form, **change}).status_code == 422
    with factory() as session:
        assert session.scalar(select(GrantReview)) is None

def test_stale_form_and_direct_score_override_rejected(client, factory, record):
    gid = seed(factory, record)
    form = review_form(client, gid, verify_geographic_restrictions="yes", geographic_restrictions="California")
    form["source_revision"] = "old"
    assert client.post(f"/grants/{gid}/verify", data=form).status_code == 409
    with pytest.raises(ValueError):
        validate_facts(record.model_dump(mode="json"), {"fit_score": 100})
    assert client.post(f"/grants/{gid}/verify", data={}).status_code == 403

def test_source_management_and_terms_gate(client, factory, monkeypatch):
    monkeypatch.setattr("grantiq.app.routes.research.validate_public_url", lambda url: ("example.org", ["93.184.216.34"]))
    token = csrf(client, "/sources/new")
    values = {"csrf_token": token, "name": "Local Foundation", "url": "https://example.org/opportunity", "selectors": "{}", "enabled": "yes"}
    assert client.post("/sources/save", data=values).status_code == 422
    response = client.post("/sources/save", data={**values, "terms_reviewed": "yes", "reviewed_by": "Source Administrator"})
    assert response.status_code == 200, response.text
    with factory() as session:
        source = session.scalar(select(ApprovedSource))
        sid = source.id
        assert source.enabled and source.terms_reviewed
    assert client.get(f"/sources/{sid}/edit").status_code == 200
    assert client.post("/sources/save", data={**values, "terms_reviewed":"yes", "reviewed_by":"Source Administrator"}).status_code == 409
    assert client.post(f"/sources/{sid}/disable", data={"csrf_token":token}).status_code == 200
    with factory() as session:
        assert not session.get(ApprovedSource, sid).enabled

def test_source_management_refuses_private_targets(client):
    token = csrf(client, "/sources/new")
    response = client.post("/sources/save", data={"csrf_token":token,"name":"Invalid", "url":"https://127.0.0.1/private", "selectors":"{}"})
    assert response.status_code == 422

def test_generic_structured_fields_and_stable_source_identity():
    source = GenericScraperSource({"name":"Renamable Foundation","url":"https://example.org/grant", "source_key":"Approved page 7", "selectors":{"geography":".place", "applicant_types":".applicant", "populations":".population", "geography_scope":".scope", "grant_status":".status"}})
    try:
        record = source.normalize_grant({"text":'<h1>Community health grant</h1><main>Funding free preventive vision care services in local schools and community clinics.</main><p class="place">Florida</p><p class="applicant">501(c)(3) nonprofit</p><p class="population">children</p><span class="scope">state</span><span class="status">posted</span>'})
        assert record.source == "Approved page 7" and record.funder_name == "Renamable Foundation"
        assert record.geographic_restrictions == ["Florida"] and record.populations_served == ["children"]
        assert record.geography_scope == "state" and record.grant_status == "posted"
    finally:
        source.close()
