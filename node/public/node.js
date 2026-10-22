const statusElement = document.querySelector('[data-status]');
if (statusElement) {
  const update = async () => {
    try {
      const r = await fetch('/api/search-status', {
        headers: { Accept: 'application/json' },
        cache: 'no-store',
      });
      if (!r.ok) throw new Error();
      const s = await r.json();
      statusElement.textContent = s.running
        ? 'Search running'
        : `Worker ${s.worker} · ${s.schedule.enabled ? 'Every ' + s.schedule.interval_hours + ' hours' : 'Paused'} · Last result: ${s.latest?.status || 'No searches yet'} · Next: ${s.schedule.enabled ? s.schedule.next_run_at : 'Paused'}`;
    } catch {
      statusElement.textContent =
        'Search status unavailable. Check the server connection or sign in again.';
    }
  };
  setInterval(update, 15000);
}
