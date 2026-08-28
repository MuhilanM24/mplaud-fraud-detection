/* Alert Center: filterable/sortable list + drill-down detail */
const Alerts = {
  state: { band: '', district: '', agency: '', flagged: '', search: '', rule: '', fff: '', sort: 'risk_desc', page: 1, perPage: 25 },

  async render() {
    const el = document.getElementById('tab-alerts');
    el.innerHTML = spinner('Loading alerts');
    if (!this._districts) {
      const projs = await API.get('/api/projects?limit=0');
      this._districts = [...new Set(projs.projects.map(p => p.district).filter(Boolean))].sort();
      this._agencies = [...new Set(projs.projects.map(p => p.agency).filter(Boolean))].sort();
    }
    el.innerHTML = `
      <div class="controls">
        <div><label>Band</label><select id="f-band">
          <option value="">All</option>
          ${['Low', 'Moderate', 'High', 'Critical'].map(b => `<option ${this.state.band === b ? 'selected' : ''}>${b}</option>`).join('')}
        </select></div>
        <div><label>District</label><select id="f-district"><option value="">All</option>
          ${this._districts.map(d => `<option ${this.state.district === d ? 'selected' : ''}>${esc(d)}</option>`).join('')}</select></div>
        <div><label>Agency</label><select id="f-agency"><option value="">All</option>
          ${this._agencies.map(a => `<option ${this.state.agency === a ? 'selected' : ''}>${esc(a)}</option>`).join('')}</select></div>
        <div><label>Status</label><select id="f-flagged">
          <option value="">All</option>
          <option value="true" ${this.state.flagged === 'true' ? 'selected' : ''}>Flagged</option>
          <option value="false" ${this.state.flagged === 'false' ? 'selected' : ''}>Not flagged</option>
        </select></div>
        <div><label>Rule</label><select id="f-rule">
          <option value="">Any</option>
          <option value="R1_COMPLETION_BEFORE_PAYMENT" ${this.state.rule === 'R1_COMPLETION_BEFORE_PAYMENT' ? 'selected' : ''}>R1 · payment &lt; 75% completion</option>
          <option value="R2_INSUFFICIENT_EVIDENCE" ${this.state.rule === 'R2_INSUFFICIENT_EVIDENCE' ? 'selected' : ''}>R2 · insufficient evidence</option>
        </select></div>
        <div><label>Fund-flow flag</label><select id="f-fff">
          <option value="">Any</option>
          ${['leakage', 'structuring', 'stage_delay', 'missing_uc'].map(t =>
            `<option value="${t}" ${this.state.fff === t ? 'selected' : ''}>${t}</option>`).join('')}
        </select></div>
        <div><label>Search</label><input type="text" id="f-search" placeholder="id, work, MP…" value="${esc(this.state.search)}"></div>
        <div><label>Sort</label><select id="f-sort">
          <option value="risk_desc">Risk ↓</option><option value="risk_asc">Risk ↑</option>
        </select></div>
        <div><button class="btn" id="f-apply">Apply</button></div>
      </div>
      <div id="alerts-table"></div>`;

    el.querySelector('#f-apply').onclick = () => {
      this.state.band = el.querySelector('#f-band').value;
      this.state.district = el.querySelector('#f-district').value;
      this.state.agency = el.querySelector('#f-agency').value;
      this.state.flagged = el.querySelector('#f-flagged').value;
      this.state.rule = el.querySelector('#f-rule').value;
      this.state.fff = el.querySelector('#f-fff').value;
      this.state.search = el.querySelector('#f-search').value;
      this.state.sort = el.querySelector('#f-sort').value;
      this.state.page = 1;
      this.loadTable();
    };
    el.querySelector('#f-search').addEventListener('keydown', (e) => { if (e.key === 'Enter') el.querySelector('#f-apply').click(); });
    await this.loadTable();
  },

  async loadTable() {
    const box = document.getElementById('alerts-table');
    box.innerHTML = spinner('Scoring projects');
    const st = this.state;
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries({ band: st.band, district: st.district,
      agency: st.agency, flagged: st.flagged, search: st.search, rule: st.rule,
      fund_flow_flag: st.fff, sort: st.sort })) {
      if (v !== '' && v != null) q.set(k, v);
    }
    q.set('limit', '0');
    const data = await API.get('/api/projects?' + q);
    this._rows = data.projects;
    const pages = Math.max(1, Math.ceil(data.total / st.perPage));
    st.page = Math.min(st.page, pages);
    const slice = this._rows.slice((st.page - 1) * st.perPage, st.page * st.perPage);
    box.innerHTML = `
      <div class="hint" style="margin-bottom:8px">${data.total} projects match · click a row for the investigation drill-down</div>
      <div class="table-wrap"><table>
        <thead><tr><th>Project</th><th>Work</th><th>District</th><th>Agency</th>
        <th>Risk</th><th>Band</th><th>Status</th><th>Rules</th><th>Fund-flow</th><th>Dup?</th></tr></thead>
        <tbody>
        ${slice.map(p => `
          <tr data-pid="${esc(p.project_id)}" style="cursor:pointer">
            <td class="mono">${esc(p.project_id)}</td>
            <td class="wrap">${esc((p.work_description || '').slice(0, 70))}</td>
            <td>${esc(p.district || '—')}</td>
            <td class="wrap">${esc((p.agency || '—').slice(0, 34))}</td>
            <td>${scorePill(p.risk_score, p.band)}</td>
            <td>${bandChip(p.band)}</td>
            <td>${statusLine(p.flagged, p.status)}</td>
            <td>${p.n_rule_violations ? `<b style="color:var(--high)">${p.n_rule_violations}</b>` : '0'}</td>
            <td>${p.n_fundflow_flags ? `<b style="color:var(--critical)">${p.n_fundflow_flags}</b>` : '—'}</td>
            <td>${p.has_duplicates ? '⚠' : ''}</td>
          </tr>`).join('')}
        </tbody></table></div>
      <div class="pager">
        <button class="btn small secondary" id="pg-prev" ${st.page <= 1 ? 'disabled' : ''}>← Prev</button>
        <span>Page ${st.page} / ${pages}</span>
        <button class="btn small secondary" id="pg-next" ${st.page >= pages ? 'disabled' : ''}>Next →</button>
      </div>`;
    box.querySelectorAll('tr[data-pid]').forEach(tr => tr.onclick = () => Alerts.drilldown(tr.dataset.pid));
    const prev = box.querySelector('#pg-prev'), next = box.querySelector('#pg-next');
    if (prev) prev.onclick = () => { st.page--; this.loadTable(); };
    if (next) next.onclick = () => { st.page++; this.loadTable(); };
  },

  async drilldown(pid) {
    modal(spinner('Fetching investigation file'));
    const p = await API.get('/api/projects/' + encodeURIComponent(pid));
    const r = p.risk;
    const ff = p.fund_flow;
    const html = `
      <button class="close" onclick="closeModal()">✕</button>
      <h2>${esc(p.project_id)} — ${esc(p.work_description || 'MPLADS work')}</h2>
      <div class="hint">${esc(p.mp_name || '—')} · ${esc(p.district || '—')} · ${esc(p.agency || '—')} · ${esc(p.work_type || '')} · ${fmtINR(p.sanctioned_amount)}</div>

      <div class="modal-section">
        <div class="gauge-wrap">
          ${riskGauge(r.risk_score, r.band)}
          <div style="flex:1">
            ${statusLine(r.flagged, r.status)}
            <table>
              <tr><td>Rule engine</td><td>${r.components.rules ?? '—'} <span class="hint">(deterministic, independent of ML)</span></td></tr>
              <tr><td>ML anomaly (IsolationForest)</td><td>${r.components.ml_anomaly ?? '—'}</td></tr>
              <tr><td>Agency history</td><td>${r.components.agency_history ?? '—'}</td></tr>
              <tr><td>Fund-flow anomalies</td><td>${r.components.fund_flow ?? '—'}</td></tr>
              <tr><td>Duplicate involvement</td><td>${r.components.duplicates ?? '—'}</td></tr>
            </table>
            ${r.floor_applied ? callout('warn', 'Score escalated by fund-flow policy floor',
              'A structural money-trail finding escalated this project into the High band even though its project-level indicators are clean.') : ''}
          </div>
        </div>
        <div style="margin-top:10px">
          <b>Plain-language reasons:</b>
          <ul>${(r.reasons || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>
        </div>
      </div>

      ${p.rule_violations.length ? `
      <div class="modal-section"><h4>Rule violations (explainable on their own)</h4>
        ${p.rule_violations.map(v => callout('rule', `${v.rule_id} [${v.severity}] — ${v.title}`, v.detail)).join('')}
      </div>` : `<div class="modal-section"><h4>Rule violations</h4>${callout('ok', 'No deterministic rule violations', 'The 75% completion-before-payment rule and evidence checks did not fire for this project.')}</div>`}
      ${p.rule_gaps.length ? callout('info', 'Rule coverage gaps', p.rule_gaps.join(' · ')) : ''}

      <div class="modal-section"><h4>Why this score — explainable AI</h4>
        <div class="hint" style="margin-bottom:6px">Method: ${esc(p.explainability.method)}</div>
        ${factorBars(p.explainability.factors)}
      </div>

      ${ff && ff.has_ledger ? `
      <div class="modal-section"><h4>Fund-flow trail</h4>${FundFlow.stepsHtml(ff)}</div>
      ${ff.flags.length ? `<div class="modal-section"><h4>Fund-flow findings</h4>${ff.flags.map(f => callout('rule', `[${f.type} · ${f.severity}] ${f.title}`, f.detail)).join('')}</div>` : callout('ok', 'Fund-flow clean', 'No leakage, structuring, abnormal parking or missing utilization certificate detected.')}` : ''}

      ${p.duplicate_pairs.length ? `
      <div class="modal-section"><h4>Potential duplicate works</h4>
        ${p.duplicate_pairs.map(d => callout('warn', `Similarity ${d.similarity} · ${d.distance_km} km apart`,
          `"${d.description_a}" ↔ "${d.description_b}" (${d.project_id_a} / ${d.project_id_b}) — possibly the same physical asset sanctioned twice (${d.mp_a} / ${d.mp_b} funds).`)).join('')}
      </div>` : ''}

      <div class="modal-section"><h4>Predictions (early warning)</h4>
        <div class="grid cols-2">
          <div>
            <b>Cost overrun</b>
            ${p.predictions.cost_overrun ? callout(p.predictions.cost_overrun.trending_over_budget ? 'warn' : 'info',
              p.predictions.cost_overrun.trending_over_budget ? 'Trending over budget' : 'Within expected range',
              p.predictions.cost_overrun.plain_language) : '<div class="hint">Not available (missing final-cost history in this dataset).</div>'}
          </div>
          <div>
            <b>Schedule slippage</b>
            ${p.predictions.delay ? callout(p.predictions.delay.delay_risk_level === 'High' ? 'warn' : 'info',
              `${p.predictions.delay.delay_risk_level} slippage risk (${(p.predictions.delay.delay_probability * 100).toFixed(0)}%)`,
              p.predictions.delay.plain_language) : '<div class="hint">Not available.</div>'}
          </div>
        </div>
      </div>

      ${p.agency_profile ? `
      <div class="modal-section"><h4>Agency risk profile — ${esc(p.agency)}</h4>
        <table>
          <tr><td>Agency risk score</td><td><b>${p.agency_profile.agency_risk_score}</b> / 100</td></tr>
          <tr><td>Portfolio</td><td>${p.agency_profile.n_projects} projects · ${p.agency_profile.flagged_projects} flagged · ${p.agency_profile.rule_violations} rule violations</td></tr>
          <tr><td>Delay rate</td><td>${p.agency_profile.delay_rate != null ? (p.agency_profile.delay_rate * 100).toFixed(0) + '%' : '—'}</td></tr>
          <tr><td>Overrun rate</td><td>${p.agency_profile.overrun_rate != null ? (p.agency_profile.overrun_rate * 100).toFixed(0) + '%' : '—'}</td></tr>
          <tr><td>Assessment</td><td>${esc(p.agency_profile.note)}</td></tr>
        </table>
      </div>` : ''}

      <div class="modal-section"><h4>Investigator feedback (human-in-the-loop)</h4>
        <div class="controls" style="margin:0">
          <input type="text" id="fb-name" placeholder="Investigator name" style="min-width:160px">
          <input type="text" id="fb-note" placeholder="Note (optional)" style="min-width:260px">
          <button class="btn ok" data-verdict="confirmed">✔ Confirmed risk</button>
          <button class="btn danger" data-verdict="false_positive">✕ False positive</button>
          <button class="btn secondary" data-verdict="needs_more_info">? Needs more info</button>
        </div>
        <div class="hint">Feedback is stored as labelled data for future model retraining (retraining itself is out of scope for this prototype).</div>
      </div>`;
    modal(html);
    document.querySelectorAll('[data-verdict]').forEach(btn => btn.onclick = async () => {
      await API.post('/api/feedback', {
        project_id: p.project_id, verdict: btn.dataset.verdict,
        investigator: document.getElementById('fb-name').value,
        note: document.getElementById('fb-note').value,
        context: { risk_score: r.risk_score, band: r.band, reasons: r.reasons,
                   rules: p.rule_violations.map(v => v.rule_id),
                   fund_flow_flags: (ff || {}).flags?.map(f => f.type) || [] },
      });
      btn.textContent = 'Saved ✓'; btn.disabled = true;
    });
  },
};
