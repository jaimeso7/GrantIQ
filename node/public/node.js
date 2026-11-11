const statusElement = document.querySelector('[data-status]');
if (statusElement) {
  // Poll only pages with a search monitor; use textContent for server-provided values.
  const update = async () => {
    try {
      const r = await fetch('/api/search-status', {
        headers: { Accept: 'application/json' },
        cache: 'no-store',
      });
      if (!r.ok) throw new Error();
      const s = await r.json();
      const next = document.querySelector('[data-next-search]');
      const frequency = document.querySelector('[data-search-frequency]');
      if (next)
        next.textContent = s.schedule.enabled
          ? new Date(s.schedule.next_run_at).toLocaleString()
          : 'Paused';
      if (frequency)
        frequency.textContent = s.schedule.enabled
          ? `Every ${s.schedule.interval_hours} hours`
          : 'Paused';
      statusElement.textContent = s.running
        ? 'Search running'
        : `Worker ${s.worker} · ${s.schedule.enabled ? 'Every ' + s.schedule.interval_hours + ' hours' : 'Paused'} · Last result: ${s.latest?.status || 'No searches yet'} · Next: ${s.schedule.enabled ? s.schedule.next_run_at : 'Paused'}`;
    } catch {
      statusElement.textContent =
        'Search status unavailable. Check the server connection or sign in again.';
    }
  };
  update();
  setInterval(update, 15000);
}
