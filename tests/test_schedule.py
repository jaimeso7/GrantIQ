from datetime import datetime, timedelta, timezone
import threading
import pytest
from test_app import factory, client, csrf
from grantiq.app.models import SearchSchedule
from grantiq.app.services.scheduler import SearchWorker, ensure_schedule, schedule_status, utc

NOW = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)

def worker_for(factory, result=None):
    clock = [NOW]
    calls = []
    def refresh(**kwargs):
        calls.append(kwargs)
        return result or {"status": "completed"}
    return SearchWorker(factory, refresh=refresh, clock=lambda: clock[0]), clock, calls

def finish(worker):
    worker.job.join(timeout=3)
    assert not worker.job.is_alive()

def test_runs_when_due_and_persists_next_run_across_restart(factory):
    worker, clock, calls = worker_for(factory)
    worker.tick()
    finish(worker)
    assert len(calls) == 1
    worker.tick()
    assert len(calls) == 1
    with factory() as session:
        assert utc(session.get(SearchSchedule, 1).next_run_at) == NOW + timedelta(hours=6)
    restarted = SearchWorker(factory, refresh=worker.refresh, clock=lambda: clock[0])
    restarted.tick()
    assert len(calls) == 1
    clock[0] += timedelta(days=2)
    restarted.tick()
    finish(restarted)
    assert len(calls) == 2  # One catch-up run, not eight missed searches.

def test_no_overlap_and_pause_does_not_abort_current_run(factory):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def refresh(**kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(3)
        return {"status": "completed"}
    worker = SearchWorker(factory, refresh=refresh, clock=lambda: NOW)
    try:
        worker.tick()
        assert entered.wait(3)
        with factory() as session:
            row = session.get(SearchSchedule, 1)
            row.next_run_at = NOW
            session.commit()
        worker.tick()
        assert len(calls) == 1
        with factory() as session:
            session.get(SearchSchedule, 1).enabled = False
            session.commit()
        release.set()
        finish(worker)
        worker.tick()
        assert len(calls) == 1
    finally:
        release.set()

@pytest.mark.parametrize('status,minutes', [('failed',15), ('busy',1)])
def test_retries_failure_or_lock_contention(factory, status, minutes):
    worker, clock, calls = worker_for(factory, {"status":status, "errors":["Test failure"]})
    worker.tick()
    finish(worker)
    with factory() as session:
        row = session.get(SearchSchedule,1)
        assert utc(row.next_run_at) == NOW + timedelta(minutes=minutes)
        assert row.last_error == 'Test failure'
    worker.tick()
    assert len(calls) == 1
    clock[0] += timedelta(minutes=minutes)
    worker.tick()
    finish(worker)
    assert len(calls) == 2

def test_crash_recovery_and_truthful_worker_health(factory):
    with factory() as session:
        row = ensure_schedule(session, NOW)
        row.last_status = 'running'
        row.next_run_at = NOW + timedelta(hours=6)
        row.heartbeat_at = NOW - timedelta(hours=1)
        session.commit()
        assert schedule_status(session, NOW)['status'] == 'Worker unavailable'
    worker, _, calls = worker_for(factory)
    worker.tick()
    finish(worker)
    assert len(calls) == 1
    with factory() as session:
        assert schedule_status(session,NOW)['worker_alive']
        assert not schedule_status(session,NOW+timedelta(minutes=2))['worker_alive']

def test_exception_records_failure_and_retry(factory):
    def fail(**kwargs):
        raise RuntimeError('Test source unavailable')
    worker = SearchWorker(factory, refresh=fail, clock=lambda: NOW)
    worker.tick()
    finish(worker)
    with factory() as session:
        row = session.get(SearchSchedule,1)
        assert row.last_status == 'failed'
        assert 'Test source unavailable' in row.last_error
        assert utc(row.next_run_at) == NOW + timedelta(minutes=15)

def test_schedule_controls_are_persistent_validated_and_csrf_protected(client, factory):
    assert 'Recurring search schedule' in client.get('/sources').text
    assert client.post('/search-schedule',data={'interval_hours':'3'}).status_code == 403
    token = csrf(client,'/sources')
    assert client.post('/search-schedule',data={'csrf_token':token,'interval_hours':'1'}).status_code == 422
    response = client.post('/search-schedule',data={'csrf_token':token,'interval_hours':'12'},follow_redirects=False)
    assert response.status_code == 303
    assert client.get('/api/search-schedule').json()['status'] == 'Paused'
    response = client.post('/search-schedule',data={'csrf_token':token,'interval_hours':'3','enabled':'yes'},follow_redirects=False)
    assert response.status_code == 303
    with factory() as session:
        row = session.get(SearchSchedule,1)
        assert row.interval_hours == 3 and row.enabled
        assert utc(row.next_run_at) <= datetime.now(timezone.utc)
