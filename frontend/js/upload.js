/* Bring-your-own-dataset mode: CSV upload -> column mapping -> analysis
   (+ optional payment-ledger upload) -> Alert-Center-style results */
const Upload = {
  dsId: null, ledgerMode: false,

  async render() {
    const el = document.getElementById('tab-upload');
    el.innerHTML = `
      <div class="note-banner">
        <b>Bring-your-own-dataset mode.</b> Upload any MPLADS project CSV — the system auto-guesses column mappings
        (fuzzy header matching), you confirm or override each one, and the <b>same rule engine + Isolation Forest +
        risk fusion</b> runs on your data via the API. Missing optional fields are defaulted with visible
        reduced-confidence notes.
      </div>
      <div class="steps" id="byo-steps">
        <span class="step active" data-s="1">1 · Upload CSV</span>
        <span class="step" data-s="2">2 · Confirm column mapping</span>
        <span class="step" data-s="3">3 · Results</span>
        <span class="step" data-s="4">4 · Optional: payment ledger</span>
      </div>
      <div id="byo-body">${this.step1Html()}</div>`;
    this.bindStep1();
  },

  step1Html() {
    return `
      <div class="card">
        <h3>Projects CSV</h3>
        <div class="dropzone" id="drop-projects">
          <div style="font-size:34px">⬆</div>
          <div><b>Drop your projects CSV here</b> or click to browse</div>
          <div class="hint" style="margin-top:6px">Required at minimum:
            <span class="mono">project_id</span>, <span class="mono">completion_pct_at_payment</span>,
            <span class="mono">geo_tag_match_score</span>, <span class="mono">site_photos_uploaded</span>.<br>
            Optional: sanctioned_amount, days_sanction_to_payment, cost_per_unit_ratio, agency_prior_flagged_count,
            district, agency, work_type, MP name, work_description, geo_lat/lon, dates…
        </div>
        <input type="file" id="file-projects" accept=".csv" hidden>
      </div>
      <div style="margin-top:12px">
        <a class="btn secondary" style="text-decoration:none;display:inline-block;padding:8px 14px" href="/api/byod/template.csv">⬇ Download projects CSV template</a>
        <a class="btn secondary" style="text-decoration:none;display:inline-block;padding:8px 14px" href="/api/byod/ledger_template.csv">⬇ Download ledger CSV template</a>
      </div>
      <div id="byo-upload-status"></div>`;
  },

  bindStep1() {
    const dz = document.getElementById('drop-projects');
    const fi = document.getElementById('file-projects');
    dz.onclick = () => fi.click();
    dz.ondragover = (e) => { e.preventDefault(); dz.classList.add('drag'); };
    dz.ondragleave = () => dz.classList.remove('drag');
    dz.ondrop = (e) => { e.preventDefault(); dz.classList.remove('drag'); this.handleFile(e.dataTransfer.files[0]); };
    fi.onchange = () => this.handleFile(fi.files[0]);
  },

  setStep(n) {
    document.querySelectorAll('#byo-steps .step').forEach(s => {
      s.classList.toggle('active', +s.dataset.s === n);
      s.classList.toggle('done', +s.dataset.s < n);
    });
  },

  async handleFile(file) {
    if (!file) return;
    const st = document.getElementById('byo-upload-status');
    st.innerHTML = spinner(`Uploading ${file.name}`);
    try {
      const meta = await API.upload('/api/byod/projects', file);
      this.dsId = meta.dataset_id;
      this.proposal = meta.proposal;
      this.headers = meta.headers;
      st.innerHTML = callout('ok', `Parsed ${meta.n_rows} rows × ${meta.headers.length} columns from ${file.name}`,
        'Review the proposed column mapping below. Auto-guessed mappings are marked with confidence; override any you disagree with, then run the analysis.');
      this.renderMapping();
    } catch (e) {
      st.innerHTML = callout('rule', 'Upload failed', e.message);
    }
  },

  renderMapping() {
    this.setStep(2);
    const fields = Object.entries(this.proposal);
    const body = document.getElementById('byo-body');
    const groups = { required: [], optional: [] };
    fields.forEach(([f, s]) => (groups[s.required ? 'required' : 'optional'].push([f, s])));
    body.insertAdjacentHTML('beforeend', `
      <div class="card" id="map-card">
        <h3>Column mapping — confirm or override every field</h3>
        <div class="map-grid">
          ${groups.required.map(([f, s]) => this.mapRow(f, s, this.headers)).join('')}
        </div>
        <h3 style="margin-top:16px">Optional fields (defaults applied if left empty)</h3>
        <div class="map-grid">
          ${groups.optional.map(([f, s]) => this.mapRow(f, s, this.headers)).join('')}
        </div>
        <div style="margin-top:14px">
          <button class="btn" id="run-analysis">Run analysis →</button>
          <span class="hint">Rules whose inputs are unmapped are reported as not-evaluable rather than silently passed.</span>
        </div>
      </div>`);
    document.getElementById('run-analysis').onclick = () => this.analyze();
  },

  mapRow(field, spec, headers) {
    const confClass = spec.confidence >= 0.8 ? 'conf-high' : spec.confidence >= 0.6 ? 'conf-mid' : 'conf-low';
    return `
      <div style="display:flex;flex-direction:column;gap:3px;padding:6px;border:1px solid var(--line);border-radius:9px">
        <div class="${spec.required ? 'req' : ''}" style="font-weight:700;font-size:12.5px">${esc(field)}</div>
        <select data-field="${esc(field)}" style="min-width:0">
          <option value="">— not in this dataset —</option>
          ${headers.map(h => `<option value="${esc(h)}" ${spec.column === h ? 'selected' : ''}>${esc(h)}</option>`).join('')}
        </select>
        <div class="conf ${confClass}">${spec.column ? `auto-guess: “${esc(spec.column)}” (${esc(spec.method)})` : 'not found — choose or leave blank'}</div>
      </div>`;
  },

  collectMapping() {
    const out = {};
    document.querySelectorAll('#map-card select[data-field]').forEach(sel => out[sel.dataset.field] = sel.value);
    return out;
  },

  async analyze() {
    const body = document.getElementById('byo-body');
    const old = document.getElementById('results-card'); if (old) old.remove();
    body.insertAdjacentHTML('beforeend', `<div class="card" id="results-card">${spinner('Running rule engine + Isolation Forest + risk fusion on your data')}</div>`);
    try {
      const res = await API.post(`/api/byod/${this.dsId}/analyze`, { mapping: this.collectMapping() });
      this.results = res;
      this.renderResults(res);
    } catch (e) {
      document.getElementById('results-card').innerHTML = callout('rule', 'Analysis failed', e.message);
    }
  },

  renderResults(res) {
    this.setStep(3);
    const card = document.getElementById('results-card');
    const s = res.summary;
    const small = res.byo.missing_optional.length ? `
      <div class="note-banner warn">
        <b>Reduced confidence:</b> ${res.byo.missing_optional.length} optional field(s) not mapped
        (${esc(res.byo.missing_optional.join(', '))}). Signals that depend on them are skipped and fusion weights are
        renormalised — anomalies are harder to separate from noise with fewer features.
        ${res.summary.confidence_notes.map(n => `<div>• ${esc(n)}</div>`).join('')}
      </div>` : '';
    card.innerHTML = `
      <h3>Results for ${esc(res.byo.filename)} — ${s.n_projects} projects</h3>
      ${small}
      <div class="note-banner">
        <b>Explainability method used for your data:</b> ${esc(res.meta.explainer)}
      </div>
      <div class="grid cols-4">
        <div class="card"><h3>Flagged for investigation</h3><div class="kpi" style="color:var(--flag)">${s.n_flagged}</div></div>
        <div class="card"><h3>High + Critical</h3><div class="kpi">${(s.band_counts.High || 0) + (s.band_counts.Critical || 0)}</div></div>
        <div class="card"><h3>Rule violations</h3><div class="kpi">${s.n_rule_violations}</div></div>
        <div class="card"><h3>Duplicate pairs</h3><div class="kpi">${s.n_duplicate_pairs}</div></div>
      </div>
      <div class="table-wrap" style="margin-top:12px"><table>
        <thead><tr><th>Project</th><th>Risk</th><th>Band</th><th>Status</th><th>Reasons (plain language)</th><th></th></tr></thead>
        <tbody>
        ${[...res.projects].sort((a, b) => b.risk.risk_score - a.risk.risk_score).map(p => `
          <tr>
            <td class="mono">${esc(p.project_id)}</td>
            <td>${scorePill(p.risk.risk_score, p.risk.band)}</td>
            <td>${bandChip(p.risk.band)}</td>
            <td>${statusLine(p.risk.flagged, p.risk.status)}</td>
            <td class="wrap"><ul style="margin:0;padding-left:16px">${p.risk.reasons.slice(0, 3).map(r => `<li>${esc(r)}</li>`).join('')}</ul></td>
            <td><button class="btn small" onclick="Upload.detail('${esc(p.project_id)}')">Detail</button></td>
          </tr>`).join('')}
        </tbody></table></div>
      <div style="margin-top:16px;border-top:1px solid var(--line);padding-top:14px">
        <h3>4 · Optional: link a payment ledger (fund-flow analytics)</h3>
        <div class="hint" style="margin-bottom:8px">CSV with project_id, stage, date or day-offset, amount — gets its own mapping step.
          Enables leakage / structuring / stage-delay / missing-UC detection and re-scores every project.</div>
        <div class="dropzone" id="drop-ledger" style="padding:18px"><b>Drop ledger CSV</b> or click to browse
          <input type="file" id="file-ledger" accept=".csv" hidden></div>
        <div id="ledger-status"></div>
      </div>`;
    const dz = card.querySelector('#drop-ledger'), fi = card.querySelector('#file-ledger');
    dz.onclick = () => fi.click();
    dz.ondragover = (e) => { e.preventDefault(); dz.classList.add('drag'); };
    dz.ondragleave = () => dz.classList.remove('drag');
    dz.ondrop = (e) => { e.preventDefault(); this.handleLedger(e.dataTransfer.files[0]); };
    fi.onchange = () => this.handleLedger(fi.files[0]);
  },

  async handleLedger(file) {
    if (!file) return;
    const st = document.getElementById('ledger-status');
    st.innerHTML = spinner('Parsing ledger');
    try {
      const meta = await API.upload(`/api/byod/${this.dsId}/ledger`, file);
      this.ledgerProposal = meta.proposal;
      this.ledgerHeaders = meta.headers;
      st.innerHTML = callout('ok', `Parsed ${meta.n_rows} ledger rows from ${file.name}`, 'Confirm the ledger column mapping:');
      st.insertAdjacentHTML('beforeend', `
        <div class="map-grid" id="ledger-map" style="margin-top:10px">
          ${Object.entries(this.ledgerProposal).map(([f, s]) => this.mapRow(f, s, this.ledgerHeaders)).join('')}
        </div>
        <button class="btn" id="ledger-apply" style="margin-top:10px">Link ledger &amp; re-analyze →</button>`);
      document.getElementById('ledger-apply').onclick = async () => {
        const mapping = {};
        document.querySelectorAll('#ledger-map select[data-field]').forEach(sel => mapping[sel.dataset.field] = sel.value);
        st.insertAdjacentHTML('beforeend', `<div id="ledger-run">${spinner('Running fund-flow analytics + re-scoring')}</div>`);
        const res = await API.post(`/api/byod/${this.dsId}/ledger/apply`, { mapping });
        document.getElementById('ledger-run').remove();
        this.renderResults(res);
        document.getElementById('results-card').scrollIntoView({ behavior: 'smooth' });
      };
    } catch (e) {
      st.innerHTML += callout('rule', 'Ledger upload failed', e.message);
    }
  },

  detail(pid) {
    const p = this.results.projects.find(x => x.project_id === pid);
    if (!p) return;
    const r = p.risk, ff = p.fund_flow;
    modal(`
      <button class="close" onclick="closeModal()">✕</button>
      <h2>${esc(p.project_id)} — uploaded-dataset risk file</h2>
      <div class="hint">${esc(p.work_description || '')} ${p.district ? '· ' + esc(p.district) : ''} ${p.agency ? '· ' + esc(p.agency) : ''}</div>
      <div class="modal-section"><div class="gauge-wrap">
        ${riskGauge(r.risk_score, r.band)}
        <div>${statusLine(r.flagged, r.status)}
          <ul style="margin-top:8px">${(r.reasons || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>
          <div class="hint">Components: ${Object.entries(r.components).map(([k, v]) => `${k}=${v}`).join(' · ')}</div>
        </div>
      </div></div>
      ${p.rule_violations.length ? `<div class="modal-section"><h4>Rule violations</h4>
        ${p.rule_violations.map(v => callout('rule', `${v.rule_id} — ${v.title}`, v.detail)).join('')}</div>` : ''}
      ${p.rule_gaps.length ? callout('info', 'Not evaluable', p.rule_gaps.join(' · ')) : ''}
      <div class="modal-section"><h4>Explainability</h4>
        <div class="hint">${esc(p.explainability.method)}</div>
        ${factorBars(p.explainability.factors)}</div>
      ${ff && ff.has_ledger ? `<div class="modal-section"><h4>Fund flow</h4>${FundFlow.stepsHtml(ff)}
        ${ff.flags.map(f => callout('rule', `[${f.type}] ${f.title}`, f.detail)).join('')}</div>` : ''}
      <div class="modal-section"><h4>Investigator feedback</h4>
        <div class="controls" style="margin:0">
          <input type="text" id="fb-name2" placeholder="Investigator" style="min-width:140px">
          <button class="btn ok" id="fb2-confirm">✔ Confirmed risk</button>
          <button class="btn danger" id="fb2-fp">✕ False positive</button>
          <button class="btn secondary" id="fb2-info">? Needs more info</button>
        </div></div>`);
    const send = async (verdict) => {
      await API.post('/api/feedback', {
        project_id: p.project_id, verdict, dataset_id: this.dsId,
        investigator: document.getElementById('fb-name2').value || 'uploaded-dataset',
        context: { risk_score: r.risk_score, band: r.band, reasons: r.reasons },
      });
      modal('<button class="close" onclick="closeModal()">✕</button><h2>Feedback saved ✓</h2><div class="hint">Stored as labelled data for future retraining.</div>');
    };
    document.getElementById('fb2-confirm').onclick = () => send('confirmed');
    document.getElementById('fb2-fp').onclick = () => send('false_positive');
    document.getElementById('fb2-info').onclick = () => send('needs_more_info');
  },
};
