(function () {
  const PRESETS = {
    '24h': () => ({ from: isoAgo(1 * 3600 * 1000) }),
    '7d':  () => ({ from: isoAgo(7 * 24 * 3600 * 1000) }),
    '30d': () => ({ from: isoAgo(30 * 24 * 3600 * 1000) }),
    'all': () => ({}),
  };

  function isoAgo(ms) { return new Date(Date.now() - ms).toISOString(); }

  function qs(params) {
    const entries = Object.entries(params).filter(([, v]) => v != null);
    return entries.length ? '?' + new URLSearchParams(entries).toString() : '';
  }

  async function fetchJson(path, params) {
    const r = await fetch(path + qs(params));
    if (!r.ok) throw new Error(`${path} returned ${r.status}`);
    return r.json();
  }

  function fmtInt(n) { return new Intl.NumberFormat().format(n); }
  function fmtPct(x) { return (x * 100).toFixed(1) + '%'; }

  // --- Health ---
  function renderHealth(data) {
    document.querySelector('[data-metric="ingested"]').textContent = fmtInt(data.ingested);
    document.querySelector('[data-metric="duplicates"]').textContent = fmtInt(data.duplicates);
    document.querySelector('[data-metric="duplicate_rate"]').textContent =
      data.ingested > 0 ? fmtPct(data.duplicate_rate) : '';
    document.querySelector('[data-metric="processed"]').textContent = fmtInt(data.processed);
    document.querySelector('[data-metric="failed"]').textContent = fmtInt(data.failed);
  }

  // --- Funnel ---
  let funnelChart = null;
  function renderFunnel(data) {
    const empty = data.steps.every(s => s.count === 0);
    document.getElementById('funnel-empty').classList.toggle('hidden', !empty);
    document.getElementById('funnel-chart').classList.toggle('hidden', empty);
    if (empty) return;

    const ctx = document.getElementById('funnel-canvas').getContext('2d');
    if (funnelChart) funnelChart.destroy();
    funnelChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.steps.map(s => s.event_name),
        datasets: [{
          data: data.steps.map(s => s.count),
          backgroundColor: '#2563eb',
          borderRadius: 6,
        }],
      },
      options: {
        indexAxis: 'y',
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const step = data.steps[ctx.dataIndex];
                const conv = step.conversion_from_top != null
                  ? ` (${fmtPct(step.conversion_from_top)})`
                  : '';
                return `${fmtInt(step.count)}${conv}`;
              },
            },
          },
        },
        scales: {
          x: { beginAtZero: true, grid: { color: '#f1f5f9' } },
          y: { grid: { display: false } },
        },
      },
    });
  }

  // --- Events time series ---
  let eventsChart = null;
  function renderEvents(data) {
    const empty = data.series.length === 0;
    document.getElementById('events-empty').classList.toggle('hidden', !empty);
    document.getElementById('events-canvas').classList.toggle('hidden', empty);
    if (empty) return;

    const dates = [...new Set(data.series.map(r => r.date))].sort();
    const names = ['page_view', 'cta_click', 'form_submit'];
    const colors = { page_view: '#2563eb', cta_click: '#0891b2', form_submit: '#16a34a' };
    const byKey = {};
    data.series.forEach(r => { byKey[`${r.date}|${r.event_name}`] = r.count; });

    const datasets = names.map(name => ({
      label: name,
      data: dates.map(d => byKey[`${d}|${name}`] || 0),
      borderColor: colors[name],
      backgroundColor: colors[name],
      tension: 0.25,
      borderWidth: 2,
      pointRadius: 3,
    }));

    const ctx = document.getElementById('events-canvas').getContext('2d');
    if (eventsChart) eventsChart.destroy();
    eventsChart = new Chart(ctx, {
      type: 'line',
      data: { labels: dates, datasets },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { position: 'bottom', labels: { boxWidth: 12 } } },
        scales: {
          x: { grid: { display: false } },
          y: { beginAtZero: true, grid: { color: '#f1f5f9' } },
        },
      },
    });
  }

  // --- UTM table ---
  function renderUtm(data) {
    const tbody = document.getElementById('utm-tbody');
    const empty = data.rows.length === 0;
    document.getElementById('utm-empty').classList.toggle('hidden', !empty);
    tbody.parentElement.parentElement.classList.toggle('hidden', empty);
    tbody.innerHTML = '';
    if (empty) return;

    for (const row of data.rows) {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="py-2">${row.utm_source ?? '<span class="text-slate-400">(direct)</span>'}</td>
        <td class="py-2">${row.utm_medium ?? '<span class="text-slate-400">(direct)</span>'}</td>
        <td class="py-2 text-right tabular-nums">${fmtInt(row.events)}</td>
        <td class="py-2 text-right tabular-nums">${fmtInt(row.leads)}</td>
      `;
      tbody.appendChild(tr);
    }
  }

  // --- Orchestration ---
  async function loadAll(preset) {
    const params = PRESETS[preset]();
    try {
      const [health, funnel, events, utm] = await Promise.all([
        fetchJson('/api/stats/health', params),
        fetchJson('/api/stats/funnel', params),
        fetchJson('/api/stats/events', params),
        fetchJson('/api/stats/utm', params),
      ]);
      renderHealth(health);
      renderFunnel(funnel);
      renderEvents(events);
      renderUtm(utm);
    } catch (err) {
      console.error('Failed to load dashboard data:', err);
    }
  }

  function setActivePreset(btn) {
    document.querySelectorAll('.preset-btn').forEach(b => {
      b.classList.remove('bg-slate-900', 'text-white');
      b.classList.add('text-slate-600', 'hover:bg-slate-200');
    });
    btn.classList.remove('text-slate-600', 'hover:bg-slate-200');
    btn.classList.add('bg-slate-900', 'text-white');
  }

  document.getElementById('preset-nav').addEventListener('click', (e) => {
    const btn = e.target.closest('.preset-btn');
    if (!btn) return;
    setActivePreset(btn);
    loadAll(btn.dataset.range);
  });

  loadAll('30d');
})();
