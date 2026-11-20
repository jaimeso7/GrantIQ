"""990-PF foundation prospects: import from the research file and the Discover view."""
import json
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from grantiq.app.database import build_engine, initialize
from grantiq.app.models import FoundationProspect
from grantiq.app.services.foundations import filter_prospects, import_prospects, sync_prospects

def gift(score, recipient, purpose, amount, **extra):
    return {"score": score, "recipient": recipient, "purpose": purpose, "amount": amount,
            "shared_subjects": extra.pop("shared", []), "focus": "prevention of blindness and vision loss",
            "city": "JACKSONVILLE", "state": "FL", "status": "paid", "to_us": False, **extra}

PROSPECTS = {
    "year": 2026, "generated_for": "Example Vision Nonprofit", "foundations_in_directory": 3,
    "filings_parsed": 3, "relevance_threshold": 0.45, "focus_phrases": ["prevention of blindness and vision loss"],
    "prospects": [
        {"ein": "11111111", "name": "EYE CARE FAMILY FOUNDATION", "city": "JACKSONVILLE", "assets": 5000000,
         "total_paid": 250000, "paid_count": 2, "relevant_total": 50000, "relevant_count": 1,
         "already_funder": False, "known_as": "", "funded_us": False, "tax_period": "2025-12-31", "object_id": "1",
         "best_match": gift(.62, "PREVENTION OF BLINDNESS SOCIETY", "CHILDREN VISION SCREENING", 50000, shared=["vision"]),
         "gifts": [gift(.62, "PREVENTION OF BLINDNESS SOCIETY", "CHILDREN VISION SCREENING", 50000, shared=["vision"]),
                   gift(.20, "CITY BALLET", "ARTS", 200000)]},
        {"ein": "222222222", "name": "LOYAL SUPPORTER TRUST", "city": "PONTE VEDRA", "assets": 900000,
         "total_paid": 30000, "paid_count": 1, "relevant_total": 30000, "relevant_count": 1,
         "already_funder": True, "known_as": "Loyal Supporter Trust", "funded_us": True, "tax_period": "2025-06-30", "object_id": "2",
         "received": [{"fiscal_year": "2024-2025", "amount": 30000, "program": "Eye exams", "flag": ""},
                      {"fiscal_year": "2025-2026", "amount": 25000, "program": "", "flag": "shown as '$25,000.00)' in the export"}],
         "received_total": 55000,
         "best_match": gift(.5, "EXAMPLE VISION NONPROFIT", "EYE EXAMS", 30000, to_us=True),
         "gifts": [gift(.5, "EXAMPLE VISION NONPROFIT", "EYE EXAMS", 30000, to_us=True)]},
        {"ein": "333333333", "name": "QUIET FOUNDATION", "city": "JACKSONVILLE", "assets": 0,
         "total_paid": 0, "paid_count": 0, "relevant_total": 0, "relevant_count": 0,
         "already_funder": False, "known_as": "", "funded_us": False, "tax_period": "", "object_id": "3",
         "grants_in_attachment": True, "tier": 2, "nefl_count": 1, "nefl_total": 2500,
         "declined": "Quiet Foundation",
         "best_match": None, "gifts": []},
    ],
}

@pytest.fixture
def factory():
    engine = build_engine("sqlite:///:memory:")
    initialize(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()

@pytest.fixture
def research_file(tmp_path):
    path = tmp_path / "irs990_prospects.json"
    path.write_text(json.dumps(PROSPECTS))
    return path

@pytest.fixture
def client(factory, research_file, monkeypatch):
    monkeypatch.setenv("GRANTIQ_IRS990_FILE", str(research_file))
    monkeypatch.setenv("GRANTIQ_ALLOWED_HOSTS", "localhost,testserver")
    monkeypatch.delenv("GRANTIQ_ADMIN_PASSWORD", raising=False)
    with factory() as session:
        import_prospects(session, research_file)
    from grantiq.app.main import create_app
    with TestClient(create_app(factory), client=("127.0.0.1", 12345)) as client:
        yield client

def test_import_pads_eins_and_keeps_every_gift(factory, research_file):
    with factory() as session:
        assert import_prospects(session, research_file) == 3
        row = session.get(FoundationProspect, "011111111")
        assert row.best_score == .62 and len(row.gifts) == 2 and row.filing_year == 2026

def test_sync_imports_once_per_file_version_and_replaces_rows(factory, research_file):
    with factory() as session:
        assert sync_prospects(session, research_file) == 3
        assert sync_prospects(session, research_file) is None
        smaller = {**PROSPECTS, "prospects": PROSPECTS["prospects"][:1]}
        research_file.write_text(json.dumps(smaller))
        stat = research_file.stat()
        os.utime(research_file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
        assert sync_prospects(session, research_file) == 1
        assert session.scalar(select(func.count()).select_from(FoundationProspect)) == 1

def test_sync_without_a_research_file_does_nothing(factory, tmp_path):
    with factory() as session:
        assert sync_prospects(session, tmp_path / "missing.json") is None

def test_filters_by_relationship_score_and_grant_purpose(factory, research_file):
    with factory() as session:
        import_prospects(session, research_file)
        names = lambda filters: [r.name for r in filter_prospects(session, filters)]
        assert names({}) == ["EYE CARE FAMILY FOUNDATION", "LOYAL SUPPORTER TRUST", "QUIET FOUNDATION"]
        assert names({"relationship": "new"}) == ["EYE CARE FAMILY FOUNDATION"]  # Quiet said no
        assert names({"relationship": "declined"}) == ["QUIET FOUNDATION"]
        assert names({"relationship": "known"}) == ["LOYAL SUPPORTER TRUST"]
        assert names({"min_score": "55"}) == ["EYE CARE FAMILY FOUNDATION"]
        assert names({"q": "blindness"}) == ["EYE CARE FAMILY FOUNDATION"]
        assert names({"city": "PONTE VEDRA"}) == ["LOYAL SUPPORTER TRUST"]
        assert names({"min_score": "not a number"}) == names({})
        assert names({"relationship": "unscorable"}) == ["QUIET FOUNDATION"]
        assert names({"area": "florida"}) == ["QUIET FOUNDATION"]
        assert names({"area": "local"}) == ["EYE CARE FAMILY FOUNDATION", "LOYAL SUPPORTER TRUST"]

def test_foundation_view_is_separate_from_grant_opportunities(client):
    foundations = client.get("/?view=foundations")
    assert foundations.status_code == 200
    assert "Eye Care Family Foundation" in foundations.text and "Has funded you" in foundations.text
    assert 'name="view" value="foundations"' in foundations.text
    grants = client.get("/")
    assert grants.status_code == 200 and "Eye Care Family Foundation" not in grants.text
    assert "990 foundations" in grants.text

def test_foundation_detail_explains_every_grant(client):
    response = client.get("/foundations/11111111")
    assert response.status_code == 200
    assert "Prevention Of Blindness Society" in response.text and "City Ballet" in response.text
    assert "relevant-row" in response.text
    assert client.get("/foundations/999999999").status_code == 404

def test_empty_foundation_view_explains_how_to_load_data(factory, monkeypatch):
    monkeypatch.setenv("GRANTIQ_ALLOWED_HOSTS", "localhost,testserver")
    monkeypatch.delenv("GRANTIQ_ADMIN_PASSWORD", raising=False)
    from grantiq.app.main import create_app
    with TestClient(create_app(factory), client=("127.0.0.1", 12345)) as client:
        assert "No 990 research has been loaded yet" in client.get("/?view=foundations").text

def test_received_grants_and_unitemized_filings_are_shown(client):
    known = client.get("/foundations/222222222").text
    assert "$55,000" in known and "2024-2025" in known and "Confirm amount" in known
    assert "Prevention of blindness and vision loss" in known
    quiet = client.get("/foundations/333333333").text
    assert "Grant list not itemized" in quiet and "does not publish as data" in quiet
    assert "Elsewhere in Florida" in quiet and "$2,500" in quiet
    assert "Said no" in quiet and "list of funders who said no" in quiet
    assert "Said no" not in client.get("/foundations/11111111").text

def test_import_rebuilds_a_table_from_an_older_version(factory, research_file):
    from sqlalchemy import text
    with factory() as session:
        session.execute(text("DROP TABLE foundation_prospects"))
        session.execute(text("CREATE TABLE foundation_prospects (ein VARCHAR(9) PRIMARY KEY, name TEXT)"))
        session.commit()
        assert import_prospects(session, research_file) == 3
        assert session.get(FoundationProspect, "222222222").received_total == 55000
