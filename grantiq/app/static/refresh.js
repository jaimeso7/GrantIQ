// Status-only polling: never navigate away from unsaved staff work.
(() => {
  const write = (key, value) => document.querySelectorAll(`[data-search-${key}]`).forEach(el => { el.textContent = value; });
  const date = value => value ? new Date(value).toLocaleString(undefined, {month:'short', day:'numeric', hour:'numeric', minute:'2-digit', timeZoneName:'short'}) : 'Not yet';
  let initialFinished;
  let polling = false;
  async function poll() {
    if (polling) return;
    polling = true;
    try {
      const response = await fetch('/api/search-schedule', {credentials:'same-origin', signal:AbortSignal.timeout(15000)});
      if (!response.ok || response.redirected) throw new Error('Status unavailable');
      const state = await response.json();
      const run = state.latest;
      document.querySelectorAll('form[action="/refresh"] button').forEach(button => {
        button.disabled = run?.status === 'running' && state.worker_alive;
        button.textContent = button.disabled ? 'Search in progress' : 'Search now';
      });
      write('status', state.status);
      write('frequency', state.enabled ? `Every ${state.interval_hours} hours` : 'Paused');
      write('next', state.enabled ? date(state.next_run_at) : 'Schedule paused');
      write('last', run ? date(run.started_at) : 'First search pending');
      write('result', run ? `${run.status} · ${run.added} new · ${run.updated} updated${run.status === 'running' ? ` · ${run.found} processed` : ''}` : 'No search completed yet');
      let message = 'Searches continue while the app server runs, even when this browser is closed.';
      if (!state.worker_alive) message = 'The search worker has not checked in. Scheduled searches need the app server running.';
      else if (!state.enabled) message = 'Automatic searches are paused. You can still refresh manually.';
      else if (state.last_status === 'failed') message = 'The last scheduled search failed. A retry is scheduled; see Data sources for details.';
      else if (run?.status === 'partial') message = 'Partial coverage: a record limit or collection issue was reported. See Data sources for details.';
      else if (run?.status === 'running') message = `Searching official sources now. ${run.found} opportunities processed so far.`;
      write('message', message);
      const finished = run?.finished_at || '';
      if (initialFinished === undefined) initialFinished = finished;
      else if (finished && finished !== initialFinished) document.querySelectorAll('[data-search-results-link]').forEach(el => { el.hidden = false; });
    } catch (_) {
      write('status', 'Connection unavailable');
      write('message', 'Live search status is unavailable. Check that the app server is running. The displayed times may be out of date.');
    } finally { polling = false; }
  }
  poll();
  setInterval(() => { if (!document.hidden) poll(); }, 15000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
})();
