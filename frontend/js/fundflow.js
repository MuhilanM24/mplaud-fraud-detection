/* Fund-flow tracker tab: stage stepper + money-trail findings */
const FundFlow = {
  async render() {
    const el = document.getElementById('tab-fundflow');
    el.innerHTML = spinner('Loading fund-flow analytics');
    const projs = await API.get('/api/projects?limit=0&sort=risk_desc');
    const withFF = projs.projects.filter(p => p.n_fundflow_flags > 0);
    const pick = this._pid;
    el.innerHTML = `
      <div class="note-banner">
        <b>Money-trail analytics.</b> Sanction → District release → Agency release → Vendor payment → Utilization certificate.
        These checks catch risk that project-level completion checks <b>cannot see</b> — e.g. a project paid at 95% completion
        (fully rule-compliant) but with payments structured just under the scrutiny threshold underneath.
      </div>
      <div class="controls">
        <div><label>Project</label><select id="ff-pick">
          ${projs.projects.map(p => `<option value="${esc(p.project_id)}" ${pick === p.project_id ? 'selected' : ''}>
            ${esc(p.project_id)} — ${(p.work_description || '').slice(0, 44)} ${p.n_fundflow_flags ? `(${p.n_fundflow_flags} flags)` : ''}</option>`).join('')}
        </select></div>
        <button class="btn" id="ff-load">Load trail</button>
      </div>
      <div class="grid cols-4" style="margin:10px 0">
        <div class="card"><h3>Projects with fund-flow flags</h3><div class="kpi" style="color:var(--critical)">${withFF.length}</div></div>
        <div class="card"><h3>Structuring patterns</h3><div class="kpi">${withFF.filter(p => p.risk_score >= 55).length}</div><div class="hint">see Compliance tab for type breakdown</div></div>
      </div>
      <div id="ff-detail"></div>`;
    const load = async () => {
      this._pid = el.querySelector('#ff-pick').value;
      document.getElementById('ff-detail').innerHTML = spinner('Tracing money');
      const d = await API.get('/api/fundflow/' + encodeURIComponent(this._pid));
      document.getElementById('ff-detail').innerHTML = d.fund_flow && d.fund_flow.has_ledger ? `
        <div class="card">
          <h3>${esc(d.project_id)} — ${esc(d.work_description || '')}</h3>
          ${this.stepsHtml(d.fund_flow)}
          ${d.fund_flow.flags.length
            ? d.fund_flow.flags.map(f => callout('rule', `[${f.type} · ${f.severity}] ${f.title}`, f.detail)).join('')
            : callout('ok', 'No money-trail anomalies', 'Amounts moved through stages within tolerance and normal timeframes; utilization certificate on file.')}
        </div>` : callout('info', 'No ledger linked', 'This project has no payment-ledger rows; fund-flow analytics need a linked ledger.');
    };
    el.querySelector('#ff-load').onclick = load;
    if (pick) await load();
  },

  stepsHtml(ff) {
    const flaggedStages = new Set();
    for (const f of ff.flags) {
      if (f.evidence?.from_stage) flaggedStages.add(f.evidence.from_stage);
      if (f.evidence?.to_stage) flaggedStages.add(f.evidence.to_stage);
      if (f.evidence?.stage) flaggedStages.add(f.evidence.stage);
    }
    return `<div class="flow">
      ${ff.stages.map((s, i) => `
        <div class="flow-step ${flaggedStages.has(s.stage) ? 'suspect' : ''}">
          <div class="node ${flaggedStages.has(s.stage) ? 'flagged' : ''}">
            <div class="stage">${i + 1}. ${esc(s.label)}</div>
            <div class="amt">${fmtINR(s.amount)}</div>
            <div class="meta">day ${s.day_offset}${i > 0 ? ` · gap ${s.gap_days}d` : ' · start'}${s.note ? `<br>${esc(s.note)}` : ''}</div>
          </div>
        </div>`).join('')}
    </div>
    <div class="hint">Suspicious hand-offs are outlined in red. Amounts at each stage, with elapsed days between hand-offs.</div>`;
  },
};
