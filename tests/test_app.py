from datetime import date, timedelta
import csv
import io
import re
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.orm import sessionmaker
from grantiq.app.database import build_engine, initialize
from grantiq.app.models import Grant, SourceRecord, PipelineEntry
from grantiq.app.schemas import GrantRecord, OrganizationProfile
from grantiq.app.services.scoring import score_grant
from grantiq.app.services.repository import get_profile, upsert_grant, set_profile, rescore_all
from grantiq.app.services.deduplication import canonical_url

class FixedEmbedder:
    backend_name = "Test semantic fixture"
    def similarity(self, first, second):
        return .95

@pytest.fixture
def factory():
    engine = build_engine("sqlite:///:memory:")
    initialize(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()

@pytest.fixture
def record():
    return GrantRecord(source="Test fixtures", source_id="excellent", source_url="https://example.org/eye-care",
        grant_title="Community Eye Care", funder_name="Example Foundation (fictional)",
        description="Free vision screening, eye health care and glasses for low-income children and adults.",
        eligibility_text="501(c)(3) nonprofit organizations operating in Florida may apply.", applicant_types=["501(c)(3) nonprofit"],
        geographic_restrictions=["Florida"], geography_scope="state", populations_served=["children", "adults"],
        categories=["health"], program_areas=["vision care"], award_min=10000, award_max=50000,
        deadline=date.today()+timedelta(days=60), grant_status="posted", is_demo=True)

def seed(factory, record):
    with factory() as session:
        grant, _ = upsert_grant(session, record, score_grant(record, get_profile(session), embedder=FixedEmbedder()))
        session.commit()
        return grant.id

@pytest.fixture
def client(factory, monkeypatch):
    monkeypatch.setenv("GRANTIQ_ALLOWED_HOSTS", "localhost,testserver")
    monkeypatch.delenv("GRANTIQ_ADMIN_PASSWORD", raising=False)
    from grantiq.app.main import create_app
    with TestClient(create_app(factory), client=("127.0.0.1", 12345)) as client:
        yield client

def csrf(client, url="/settings"):
    response = client.get(url)
    assert response.status_code == 200, response.text
    return re.search(r'name="csrf_token"\s+value="([^"]+)"', response.text).group(1)

def test_database_dedup_and_pipeline_preservation(factory, record):
    grant_id = seed(factory, record)
    with factory() as session:
        session.add(PipelineEntry(grant_id=grant_id, status="Applying", notes="Keep our research"))
        session.commit()
        updated = record.model_copy(update={"description": "Updated official description"})
        grant, added = upsert_grant(session, updated, score_grant(updated, get_profile(session), embedder=FixedEmbedder()))
        session.commit()
        assert not added and grant.id == grant_id
        assert grant.pipeline.notes == "Keep our research"
        duplicate = record.model_copy(update={"source": "Another approved source", "source_id": "duplicate", "source_url": "https://example.net/eye"})
        grant, added = upsert_grant(session, duplicate, score_grant(duplicate, get_profile(session), embedder=FixedEmbedder()))
        session.commit()
        assert not added and grant.id == grant_id
        assert session.scalar(select(func.count()).select_from(Grant)) == 1
        assert session.scalar(select(func.count()).select_from(SourceRecord)) == 2

def test_shared_listing_does_not_merge_different_opportunities(factory, record):
    seed(factory, record)
    seed(factory, record.model_copy(update={"grant_title": "Different Opportunity", "source_id": "different"}))
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Grant)) == 2

def test_canonical_url():
    assert canonical_url("https://EXAMPLE.org/eye/?id=2&utm_source=test#apply") == "https://example.org/eye?id=2"

def test_app_pages_filters_csv_pipeline(client, factory, record):
    gid = seed(factory, record)
    for path in ("/", f"/grants/{gid}", "/settings", "/sources", "/pipeline"):
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert "GrantIQ" in response.text
    assert record.grant_title in client.get("/?q=eye").text
    assert record.grant_title not in client.get("/?q=unmatchedkeyword").text
    token = csrf(client, f"/grants/{gid}")
    response = client.post(f"/grants/{gid}/pipeline", data={"csrf_token": token, "status": "Applying", "notes": '=HYPERLINK("https://example.org")', "assigned_to": "Research Team", "requested_amount": "20000", "application_deadline": str(date.today()+timedelta(days=45))})
    assert response.status_code == 200
    assert "Research Team" in client.get("/pipeline").text
    exported = client.get("/export.csv?pipeline_status=Applying")
    assert exported.status_code == 200
    rows = list(csv.reader(io.StringIO(exported.text.lstrip("\ufeff")))); assert len(rows) == 2
    assert any(cell.startswith("'=HYPERLINK") for cell in rows[1])
    assert len(list(csv.reader(io.StringIO(client.get("/export.csv?q=unmatchedkeyword").text)))) == 1

def test_profile_save_recalculates_and_invalid_weights_rejected(client, factory, record):
    seed(factory, record)
    token = csrf(client)
    response = client.post("/settings", data={"csrf_token": token, "service_locations": "California", "mission": "Provide vision care"})
    assert response.status_code == 200
    with factory() as session:
        assert get_profile(session).service_locations == ["California"]
        assert session.scalar(select(Grant)).assessment.eligibility_status == "Ineligible"
    response = client.post("/settings", data={"csrf_token": token, "weight_mission": "99"})
    assert response.status_code == 422
    with factory() as session:
        assert get_profile(session).weights["mission"] == 30

def test_csrf_and_html_are_safe(client, factory, record):
    gid = seed(factory, record.model_copy(update={"grant_title": "<script>alert(1)</script>"}))
    assert client.post(f"/grants/{gid}/pipeline", data={"status": "Awarded"}).status_code == 403
    text = client.get(f"/grants/{gid}").text
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text

def test_deadlines_expire_even_when_refresh_source_fails(factory, record):
    from grantiq.ingestion import run_refresh
    seed(factory, record.model_copy(update={"deadline": date.today()-timedelta(days=1)}))
    class BrokenSource:
        name = "Broken official source"
        def fetch_grants(self):
            raise RuntimeError("Temporary outage")
    result = run_refresh(sources=[BrokenSource()], session_factory=factory, embedder=FixedEmbedder())
    assert result["status"] == "failed" and result["expired"] == 1
    assert "Temporary outage" in result["errors"][0]
    with factory() as session:
        grant = session.scalar(select(Grant))
        assert grant.grant_status == "closed"
        assert grant.assessment.fit_score == 0

def test_refresh_writes_and_reports_counts(factory, record):
    from grantiq.ingestion import run_refresh
    class FixtureSource:
        name = "Fixtures"
        def fetch_grants(self):
            yield record
    first = run_refresh(sources=[FixtureSource()], session_factory=factory, embedder=FixedEmbedder())
    second = run_refresh(sources=[FixtureSource()], session_factory=factory, embedder=FixedEmbedder())
    assert first["added"] == 1 and second["updated"] == 1
    assert second["status"] == "completed"

def test_shared_access_requires_password_and_session(factory, monkeypatch):
    monkeypatch.setenv("GRANTIQ_ALLOWED_HOSTS", "testserver")
    monkeypatch.setenv("GRANTIQ_ADMIN_PASSWORD", "test-only-password")
    monkeypatch.setenv("GRANTIQ_SECRET_KEY", "test-only-secret-" * 3)
    from grantiq.app.main import create_app
    with TestClient(create_app(factory), client=("192.0.2.1", 1234)) as client:
        assert client.get("/settings", follow_redirects=False).headers["location"] == "/login"
        token = csrf(client, "/login")
        assert client.post("/login", data={"csrf_token": token, "password": "wrong"}).status_code == 401
        assert client.post("/login", data={"csrf_token": token, "password": "test-only-password"}).status_code == 200
        assert client.get("/settings").status_code == 200

def test_local_mode_rejects_network_clients(factory, monkeypatch):
    monkeypatch.setenv("GRANTIQ_ALLOWED_HOSTS", "testserver")
    monkeypatch.delenv("GRANTIQ_ADMIN_PASSWORD", raising=False)
    from grantiq.app.main import create_app
    with TestClient(create_app(factory), client=("192.0.2.1", 1234)) as client:
        assert client.get("/").status_code == 403
