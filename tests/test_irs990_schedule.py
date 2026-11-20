"""Monthly 990-PF refresh: scheduling, recovery, import, and the Sources controls."""
import json
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from grantiq.app.database import build_engine, initialize
from grantiq.app.models import FoundationProspect, Irs990Schedule
from grantiq.app.services import irs990_schedule as schedule
from grantiq.app.services.scheduler import SearchWorker

NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
RESULT = {"year": 2026, "years": [2026], "summary": {"filings_indexed": 2, "filings_parsed": 1, "archives_downloaded": ["2026_TEOS_XML_10A"]},
          "prospects": [{"ein": "123456789", "name": "EYE FOUNDATION", "best_match": None, "gifts": []}]}

@pytest.fixture
def factory():
    engine = build_engine("sqlite:///:memory:")
    initialize(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()

@pytest.fixture(autouse=True)
def pipeline(tmp_path, monkeypatch):
    script = tmp_path / "report.py"
    script.write_text("")
    output = tmp_path / "irs990_prospects.json"
    monkeypatch.setattr(schedule, "PIPELINE", script)
    monkeypatch.setattr(schedule, "DATA_DIR", tmp_path)
    monkeypatch.setenv("GRANTIQ_IRS990_FILE", str(output))
    return output

def row(factory):
    with factory() as session:
        return session.get(Irs990Schedule, 1)

def test_first_check_waits_a_day_then_runs_monthly(factory):
    with factory() as session:
        assert schedule.claim_if_due(session, NOW) is False
        assert schedule.claim_if_due(session, NOW + timedelta(days=1)) is True
        assert schedule.utc(row(factory).next_run_at) == NOW + timedelta(days=31)
        assert row(factory).last_status == "running"

def test_restart_marks_an_abandoned_run_interrupted_and_reruns_it(factory):
    with factory() as session:
        schedule.ensure_irs990_schedule(session, NOW)
        record = session.get(Irs990Schedule, 1)
        record.last_status, record.next_run_at = "running", NOW + timedelta(days=30)
        session.commit()
        assert schedule.claim_if_due(session, NOW) is True

def test_paused_or_missing_pipeline_never_runs(factory, monkeypatch, tmp_path):
    with factory() as session:
        record = schedule.ensure_irs990_schedule(session, NOW - timedelta(days=2))
        record.enabled = False
        session.commit()
        assert schedule.claim_if_due(session, NOW) is False
        record.enabled = True
        session.commit()
        monkeypatch.setattr(schedule, "PIPELINE", tmp_path / "absent.py")
        assert schedule.claim_if_due(session, NOW) is False
        assert schedule.irs990_status(session, NOW)["status"] == "Pipeline not installed"

def test_success_imports_results_and_records_the_summary(factory, pipeline):
    def runner():
        pipeline.write_text(json.dumps(RESULT))
        return True, ""
    schedule.execute(factory, clock=lambda: NOW, runner=runner)
    record = row(factory)
    assert record.last_status == "success" and record.last_summary["archives_downloaded"] == ["2026_TEOS_XML_10A"]
    with factory() as session:
        assert session.get(FoundationProspect, "123456789").name == "EYE FOUNDATION"

def test_failure_keeps_previous_results_and_retries_within_six_hours(factory, pipeline):
    pipeline.write_text(json.dumps(RESULT))
    schedule.execute(factory, clock=lambda: NOW, runner=lambda: (True, ""))
    with factory() as session:
        session.get(Irs990Schedule, 1).next_run_at = NOW + timedelta(days=30)
        session.commit()
    schedule.execute(factory, clock=lambda: NOW, runner=lambda: (False, "HTTPStatusError: 503"))
    record = row(factory)
    assert record.last_status == "failed" and "503" in record.last_error
    assert schedule.utc(record.next_run_at) == NOW + schedule.RETRY_AFTER
    assert record.last_summary["filings_parsed"] == 1
    with factory() as session:
        assert session.get(FoundationProspect, "123456789") is not None

def test_worker_starts_the_990_job_only_when_given_one(factory):
    calls = []
    clock = lambda: NOW + timedelta(days=2)
    with factory() as session:
        schedule.ensure_irs990_schedule(session, NOW)
    SearchWorker(factory, refresh=lambda **_: {"status": "success"}, clock=clock).tick()
    assert row(factory).last_status == "waiting"
    worker = SearchWorker(factory, refresh=lambda **_: {"status": "success"}, clock=clock, irs990=calls.append)
    worker.tick()
    worker.irs990_job.join(timeout=2)
    assert calls == [factory] and row(factory).last_status == "running"

def test_sources_page_controls(factory, monkeypatch):
    monkeypatch.setenv("GRANTIQ_ALLOWED_HOSTS", "localhost,testserver")
    monkeypatch.delenv("GRANTIQ_ADMIN_PASSWORD", raising=False)
    from grantiq.app.main import create_app
    with TestClient(create_app(factory), client=("127.0.0.1", 12345)) as client:
        page = client.get("/sources")
        assert page.status_code == 200 and "IRS 990 foundation research" in page.text
        token = page.text.split('name="csrf_token" value="')[1].split('"')[0]
        assert client.post("/irs990-schedule/run", data={"csrf_token": token}, follow_redirects=False).status_code == 303
        assert schedule.utc(row(factory).next_run_at) <= datetime.now(timezone.utc)
        client.post("/irs990-schedule", data={"csrf_token": token}, follow_redirects=False)
        assert row(factory).enabled is False
        assert client.get("/api/irs990-schedule").json()["status"] == "Paused"
