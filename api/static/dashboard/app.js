(function () {
  // Real-Time Ops HUD palette (matches Tailwind tokens in index.html)
  const COLORS = {
    pageView:   '#4ADE80',  // pulse / lighter green
    ctaClick:   '#22C55E',  // primary run green
    formSubmit: '#F59E0B',  // amber (high-value signal)
    grid:       'rgba(71, 85, 105, 0.25)',  // outline at low opacity
    axis:       '#94A3B8',  // dim text
    tooltipBg:  '#1E293B',  // surface
    tooltipFg:  '#F8FAFC',  // fg
    tooltipBr:  '#475569',  // outline
  };

  const MONO = 'Fira Code, ui-monospace, monospace';

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
    const pendingEl = document.querySelector('[data-metric="pending"]');
    pendingEl.textContent = fmtInt(data.pending);
    pendingEl.classList.remove('text-fg', 'text-warn');
    pendingEl.classList.add(data.pending > 0 ? 'text-warn' : 'text-fg');
    document.querySelector('[data-metric="processed"]').textContent = fmtInt(data.processed);
    const failedEl = document.querySelector('[data-metric="failed"]');
    failedEl.textContent = fmtInt(data.failed);
    failedEl.classList.remove('text-fg', 'text-err');
    failedEl.classList.add(data.failed > 0 ? 'text-err' : 'text-fg');
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

    const stepColors = [COLORS.pageView, COLORS.ctaClick, COLORS.formSubmit];

    funnelChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.steps.map(s => s.event_name),
        datasets: [{
          data: data.steps.map(s => s.count),
          backgroundColor: data.steps.map((_, i) => stepColors[i] || COLORS.ctaClick),
          borderRadius: 2,
          borderSkipped: false,
        }],
      },
      options: {
        indexAxis: 'y',
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: COLORS.tooltipBg,
            titleColor: COLORS.tooltipFg,
            bodyColor: COLORS.tooltipFg,
            borderColor: COLORS.tooltipBr,
            borderWidth: 1,
            padding: 10,
            titleFont: { family: MONO },
            bodyFont: { family: MONO },
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
          x: {
            beginAtZero: true,
            grid: { color: COLORS.grid, drawBorder: false },
            ticks: { color: COLORS.axis, font: { family: MONO } },
          },
          y: {
            grid: { display: false },
            ticks: { color: COLORS.axis, font: { family: MONO } },
          },
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
    const colors = {
      page_view:   COLORS.pageView,
      cta_click:   COLORS.ctaClick,
      form_submit: COLORS.formSubmit,
    };
    const byKey = {};
    data.series.forEach(r => { byKey[`${r.date}|${r.event_name}`] = r.count; });

    const datasets = names.map(name => ({
      label: name,
      data: dates.map(d => byKey[`${d}|${name}`] || 0),
      borderColor: colors[name],
      backgroundColor: colors[name] + '1A', // ~10% opacity fill
      tension: 0.3,
      borderWidth: 2,
      pointRadius: 3,
      pointBackgroundColor: colors[name],
      pointBorderColor: '#0F172A',
      pointBorderWidth: 2,
    }));

    const ctx = document.getElementById('events-canvas').getContext('2d');
    if (eventsChart) eventsChart.destroy();
    eventsChart = new Chart(ctx, {
      type: 'line',
      data: { labels: dates, datasets },
      options: {
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'bottom',
            labels: {
              boxWidth: 10,
              boxHeight: 10,
              color: COLORS.axis,
              font: { family: MONO, size: 11 },
              padding: 15,
            },
          },
          tooltip: {
            backgroundColor: COLORS.tooltipBg,
            titleColor: COLORS.tooltipFg,
            bodyColor: COLORS.tooltipFg,
            borderColor: COLORS.tooltipBr,
            borderWidth: 1,
            padding: 10,
            titleFont: { family: MONO },
            bodyFont: { family: MONO },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: COLORS.axis, font: { family: MONO } },
          },
          y: {
            beginAtZero: true,
            grid: { color: COLORS.grid, drawBorder: false },
            ticks: { color: COLORS.axis, font: { family: MONO } },
          },
        },
      },
    });
  }

  // --- UTM table ---
  function renderUtm(data) {
    const tbody = document.getElementById('utm-tbody');
    const empty = data.rows.length === 0;
    document.getElementById('utm-empty').classList.toggle('hidden', !empty);
    const wrapper = tbody.parentElement.parentElement;
    wrapper.classList.toggle('hidden', empty);
    tbody.innerHTML = '';
    if (empty) return;

    for (const row of data.rows) {
      const tr = document.createElement('tr');
      tr.className = 'hover:bg-elevated/50 transition-colors';
      const src = row.utm_source ?? '<span class="text-faint">(direct)</span>';
      const med = row.utm_medium ?? '<span class="text-faint">(direct)</span>';
      const leadsClass = row.leads > 0 ? 'text-run' : 'text-faint';
      tr.innerHTML = `
        <td class="py-3 text-dim">${src}</td>
        <td class="py-3 text-dim">${med}</td>
        <td class="py-3 text-right tabular-nums text-fg">${fmtInt(row.events)}</td>
        <td class="py-3 text-right tabular-nums ${leadsClass}">${fmtInt(row.leads)}</td>
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
      b.classList.remove('bg-run/10', 'border', 'border-run', 'text-run', 'rounded-sm');
      b.classList.add('text-dim', 'hover:text-run');
    });
    btn.classList.remove('text-dim', 'hover:text-run');
    btn.classList.add('bg-run/10', 'border', 'border-run', 'text-run', 'rounded-sm');
  }

  document.getElementById('preset-nav').addEventListener('click', (e) => {
    const btn = e.target.closest('.preset-btn');
    if (!btn) return;
    setActivePreset(btn);
    loadAll(btn.dataset.range);
  });

  loadAll('30d');
})();
