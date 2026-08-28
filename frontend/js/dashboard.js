/* Dashboard tab */
const Dashboard = {
  async render() {
    const el = document.getElementById('tab-dashboard');
    el.innerHTML = spinner('Running risk pipeline');
    const [meta, summary] = await Promise.all([API.get('/api/meta'), API.get('/api/summary')]);
    const s = meta.summary, m = meta.meta;
    const total = s.n_projects;
    el.innerHTML = `
      <div class="grid cols-4">
        <div class="card"><h3>Projects analysed</h3><div class="kpi">${total}</div>
          <div class="hint">${esc(s.dataset_label)} · ledger rows linked: ${s.n_fundflow_flags > 0 ? 'yes' : 'no'}</div></div>
        <div class="card"><h3>Flagged for investigation</h3><div class="kpi" style="color:var(--flag)">${s.n_flagged}</div>
          <div class="hint">${((s.n_flagged / total) * 100).toFixed(1)}% of portfolio · High + Critical bands</div></div>
        <div class="card"><h3>Rule violations</h3><div class="kpi" style="color:var(--high)">${s.n_rule_violations}</div>
          <div class="hint">deterministic checks — independent of ML</div></div>
        <div class="card"><h3>Fund-flow flags</h3><div class="kpi" style="color:var(--critical)">${s.n_fundflow_flags}</div>
          <div class="hint">leakage / structuring / delay / missing UC</div></div>
      </div>

      <div class="grid cols-2" style="margin-top:14px">
        <div class="card"><h3>Risk band distribution</h3><div id="ch-bands" class="chart"></div></div>
        <div class="card"><h3>Anomaly score vs completion-at-payment</h3><div id="ch-anom" class="chart"></div></div>
        <div class="card"><h3>Agency risk profile (top 10)</h3><div id="ch-agency" class="chart"></div></div>
        <div class="card"><h3>Explainability & model status</h3>
          <table>
            <tr><td>Anomaly model</td><td>${esc(m.anomaly.model || 'skipped')} (${(m.anomaly.features || []).length} features)</td></tr>
            <tr><td>Explainer</td><td>${esc(m.explainer)}</td></tr>
            <tr><td>Surrogate fidelity</td><td>R²=${m.surrogate_r2 ?? '—'} · MAE=${m.surrogate_mae ?? '—'}</td></tr>
            <tr><td>Delay model</td><td>${m.delay_trained ? `AUC=${m.delay_auc}` : 'not trained'}</td></tr>
            <tr><td>Overrun model</td><td>${m.overrun_trained ? `R²=${m.overrun_r2} · MAE=${m.overrun_mae}` : 'not trained'}</td></tr>
            <tr><td>NLP backend</td><td>${esc(m.nlp_backend)}</td></tr>
          </table>
          <div class="hint" style="margin-top:8px">Validated vs heuristic: <b>${esc(m.provenance.assam_validated.slice(0, 140))}…</b> ${esc(m.provenance.heuristics)}</div>
        </div>
      </div>`;

    // band distribution
    const bands = ['Low', 'Moderate', 'High', 'Critical'];
    const colors = { Low: '#2fbf71', Moderate: '#e2b93b', High: '#ef8c3a', Critical: '#e5484d' };
    Plotly.newPlot('ch-bands', [{
      x: bands, y: bands.map(b => s.band_counts[b] || 0), type: 'bar',
      marker: { color: bands.map(b => colors[b]) },
      text: bands.map(b => s.band_counts[b] || 0), textposition: 'outside',
    }], { margin: { t: 10, b: 40, l: 40, r: 10 }, paper_bgcolor: 'transparent', plot_bgcolor: 'transparent', font: { color: '#44536b' } }, { displayModeBar: false });

    // anomaly scatter
    const projs = await API.get('/api/projects?limit=0');
    const rows = projs.projects;
    Plotly.newPlot('ch-anom', [{
      x: rows.map(p => p.completion_pct_at_payment ?? 0),
      y: rows.map(p => p.ml_anomaly_score ?? 0),
      mode: 'markers', type: 'scatter',
      text: rows.map(p => `${p.project_id}<br>risk ${p.risk_score} · ${p.band}<br>${esc(p.work_description || '').slice(0, 60)}`),
      hoverinfo: 'text',
      marker: { size: 8, color: rows.map(p => colors[p.band]), opacity: .8 },
    }], {
      margin: { t: 10, b: 45, l: 45, r: 10 }, paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
      font: { color: '#44536b' }, xaxis: { title: 'Physical completion % at payment', range: [-3, 103] },
      yaxis: { title: 'ML anomaly percentile' }, showlegend: false,
      shapes: [{ type: 'line', x0: 75, x1: 75, y0: 0, y1: 100,
                 line: { color: '#e5484d', dash: 'dot', width: 1.5 } }],
    }, { displayModeBar: false });

    // agency bars
    const ags = summary.agencies.slice(0, 10);
    Plotly.newPlot('ch-agency', [{
      x: ags.map(a => a.agency_risk_score).reverse(),
      y: ags.map(a => a.agency).reverse(), orientation: 'h', type: 'bar',
      marker: { color: ags.map(a => a.agency_risk_score >= 55 ? '#e5484d' : a.agency_risk_score >= 35 ? '#ef8c3a' : '#4f8cff').reverse() },
      text: ags.map(a => `${a.agency_risk_score} · ${a.n_projects} projects`).reverse(), textposition: 'auto',
    }], {
      margin: { t: 10, b: 30, l: 260, r: 20 }, paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
      font: { color: '#44536b', size: 11 }, height: 320,
    }, { displayModeBar: false });
  },
};
