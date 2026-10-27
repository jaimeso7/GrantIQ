from datetime import date, timedelta
from sqlalchemy import select, func
from pydantic import ValidationError
import pytest
from test_app import factory, record, seed, FixedEmbedder, client, csrf
from grantiq.app.models import Grant
from grantiq.app.schemas import OrganizationProfile
from grantiq.app.services.repository import get_profile, upsert_grant, grant_view
from grantiq.app.services.scoring import score_grant

def test_revised_deadline_deduplicates_against_new_fingerprint(factory, record):
    gid = seed(factory, record)
    revised = record.model_copy(update={"deadline": record.deadline+timedelta(days=10)})
    assert seed(factory, revised) == gid
    duplicate = revised.model_copy(update={"source": "Other source", "source_id": "new-id", "source_url": "https://example.net/revised"})
    assert seed(factory, duplicate) == gid
    old_cycle = record.model_copy(update={"source_id": "old-cycle", "source_url": "https://example.org/previous-cycle"})
    assert seed(factory, old_cycle) != gid
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Grant)) == 2

def test_revision_collision_preserves_both_staff_histories(factory, record):
    first = seed(factory, record)
    revised = record.model_copy(update={"source_id": "separate", "deadline": record.deadline+timedelta(days=10)})
    second = seed(factory, revised)
    assert first != second
    assert seed(factory, revised.model_copy(update={"source_id": record.source_id})) == first
    with factory() as session:
        grant = session.get(Grant, first)
        assert any("Potential duplicate" in w for w in grant.assessment.result["warnings"])
        assert session.scalar(select(func.count()).select_from(Grant)) == 2

def test_read_time_expiry_overrides_stale_score_without_rescore(factory, record):
    gid = seed(factory, record)
    with factory() as session:
        grant = session.get(Grant, gid)
        # Simulates midnight while a refresh holds the scoring lock.
        grant.details = {**grant.details, "deadline": str(date.today()-timedelta(days=1))}
        view = grant_view(grant)
        assert view["assessment"].fit_score == 0
        assert view["assessment"].recommendation == "INELIGIBLE"
        assert all(c.points == 0 for c in view["assessment"].components)

def test_settings_reject_nonfinite_values_and_unsafe_links():
    for values in ({"annual_budget": float("nan")}, {"minimum_desired_award": float("inf")}, {"profile_source_url": "javascript:alert(1)"}):
        with pytest.raises(ValidationError):
            OrganizationProfile(**values)

def test_source_client_closed_after_refresh(factory, record):
    from grantiq.ingestion import run_refresh
    class Source:
        closed = False
        def fetch_grants(self):
            yield record
        def close(self):
            self.closed = True
    adapter = Source()
    run_refresh(sources=[adapter], session_factory=factory, embedder=FixedEmbedder())
    assert adapter.closed

def test_dashboard_serves_assets_and_refresh_button_dispatches(client, monkeypatch):
    import grantiq.ingestion
    dispatched = []
    monkeypatch.setattr(grantiq.ingestion, "run_refresh", lambda **kwargs: dispatched.append(kwargs))
    css = client.get("/static/styles.css")
    script = client.get("/static/refresh.js")
    assert css.status_code == script.status_code == 200
    assert "text/css" in css.headers["content-type"] and "@media" in css.text
    token = csrf(client, "/")
    result = client.post("/refresh", data={"csrf_token": token})
    assert result.status_code == 200 and "Refresh started" in result.text
    assert len(dispatched) == 1 and "session_factory" in dispatched[0]

def test_listing_rows_do_not_collapse_into_one_grant(factory):
    """Every row of a listing page shares source_url; only source_id separates them."""
    import httpx
    from test_sources import LISTING_URL, listing_responder, listing_source, public_dns
    with httpx.Client(transport=httpx.MockTransport(listing_responder())) as http:
        source = listing_source(http, None)
        records = list(source.fetch_grants())
    assert len({r.source_url for r in records}) == 1 and len(records) == 5
    ids = {seed(factory, item) for item in records}
    assert len(ids) == 5
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Grant)) == 5
    # A second refresh updates in place rather than duplicating.
    for item in records:
        with factory() as session:
            _, added = upsert_grant(session, item, score_grant(item, get_profile(session), embedder=FixedEmbedder()))
            session.commit()
            assert added is False
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Grant)) == 5
