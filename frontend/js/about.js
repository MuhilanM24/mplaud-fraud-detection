/* Methods & guardrails tab */
const About = {
  async render() {
    const el = document.getElementById('tab-about');
    el.innerHTML = spinner('Loading methodology');
    const meta = await API.get('/api/meta');
    const m = meta.meta, t = m.thresholds;
    el.innerHTML = `
      <div class="grid cols-2">
        <div class="card"><h3>What is validated vs. heuristic</h3>
          <div class="callout ok"><b>Validated against real findings:</b><br>${esc(m.provenance.assam_validated)}</div>
          <div class="callout warn"><b>General-purpose heuristics (NOT from the Assam case):</b><br>${esc(m.provenance.heuristics)}</div>
        </div>

        <div class="card"><h3>Rule engine — deterministic, independent of ML</h3>
          <table>
            <tr><td>R1 — completion before payment</td><td>fires when completion at payment &lt; ${t.completion_before_payment_pct}% (MPLADS guideline)</td></tr>
            <tr><td>R2 — insufficient evidence</td><td>geo-tag match &lt; ${t.geo_match_min} AND site photos &lt; ${t.photos_min}</td></tr>
          </table>
        </div>
        <div class="card"><h3>Risk fusion</h3>
          <table>
            ${Object.entries(t.fusion_weights).map(([k, v]) => `<tr><td>${k}</td><td>${(v * 100).toFixed(0)}%</td></tr>`).join('')}
            <tr><td>Bands</td><td>Low &lt;25 · Moderate &lt;50 · High &lt;75 · Critical ≥75</td></tr>
            <tr><td>Flagged</td><td>${t.flagged_bands.join(' + ')}</td></tr>
            <tr><td>Fund-flow floor policy</td><td>structuring / big leakage → ≥${t.fund_flow_floor}; stage delay / missing UC → ≥55</td></tr>
          </table>
        </div>

        <div class="card"><h3>Fund-flow checks</h3>
          <table>
            <tr><td>Leakage tolerance</td><td>amount drop &gt; ${t.leakage_tolerance_pct}% between hand-offs</td></tr>
            <tr><td>Stage parking</td><td>gap ≥ ${t.stage_delay_days} days</td></tr>
            <tr><td>Structuring</td><td>≥ ${t.structuring_min_payments} payments each ≥ 85% of Rs ${(t.structuring_threshold / 1e5).toFixed(0)}L threshold (just-under), within 30 days</td></tr>
            <tr><td>Missing UC</td><td>no utilization certificate ${t.uc_window_days}+ days after vendor payment</td></tr>
          </table>
        </div>

        <div class="card"><h3>AI methods in this build</h3>
          <table>
            <tr><td>Anomaly</td><td>IsolationForest (${m.anomaly.n_estimators ?? 300} trees, contamination ${(m.anomaly.contamination ?? 0.10).toFixed(2)}) over ${m.anomaly.features?.length ?? 8}+ features</td></tr>
            <tr><td>Explainability</td><td>${esc(m.explainer)}</td></tr>
            <tr><td>Overrun</td><td>GradientBoosting regression (R²=${m.overrun_r2 ?? '—'}), flag at predicted final/sanctioned ≥ 1.15</td></tr>
            <tr><td>Delay</td><td>GradientBoosting classifier (AUC=${m.delay_auc ?? '—'}), flag P(delay &gt; 90d)</td></tr>
            <tr><td>Duplicates</td><td>${esc(m.nlp_backend)} + DBSCAN(haversine ≤ ${t.dup_distance_km ?? 1.5} km)</td></tr>
            <tr><td>Surrogate fidelity</td><td>R²=${m.surrogate_r2 ?? '—'} (explains the fused score)</td></tr>
          </table>
        </div>
      </div>

      <div class="card" style="margin-top:14px"><h3>Demo data provenance</h3>
        <div class="hint">
          The built-in dataset is <b>synthetic</b> (deterministic, seed 42): ~180 normal projects, 6 reproducing the documented
          2023 Barpeta (Assam) MPLAD pattern — Rs 28 lakh for 3 roads under RS MP Ajit Bhuyan's fund, paid before the
          mandatory 75% completion threshold with roads never built; officials were suspended and chargesheeted — plus
          ledger-only structuring / delay / leakage / missing-UC patterns and planted duplicate works.
          See <a href="VALIDATION_REPORT.md" target="_blank">VALIDATION_REPORT.md</a> for recall metrics.
        </div>
      </div>`;
  },
};
