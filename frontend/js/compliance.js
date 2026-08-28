/* Compliance monitoring tab — early warnings as they occur */
const Compliance = {
  async render() {
    const el = document.getElementById('tab-compliance');
    el.innerHTML = spinner('Rebuilding compliance timeline');
    const d = await API.get('/api/compliance/events?limit=400');
    const typeNames = {
      R1_COMPLETION_BEFORE_PAYMENT: 'Payment before 75% completion',
      R2_INSUFFICIENT_EVIDENCE: 'Insufficient site evidence',
      leakage: 'Fund leakage between stages',
      structuring: 'Structured (split) payments',
      stage_delay: 'Funds parked abnormally',
      missing_uc: 'Utilization certificate missing',
    };
    el.innerHTML = `
      <div class="note-banner">
        <b>Compliance early-warning feed.</b> Violations surface <b>as they occur</b> (dated by the moment each check
        became detectable — payment date, or when a UC/stage window lapsed) — not months later at audit time.
        Each event is a signal for human follow-up.
      </div>
      <div class="timeline">
        ${d.events.map(e => `
          <div class="tl-item sev-${esc(e.severity)}">
            <div class="tl-date">${esc(e.date || '—')} · ${esc(typeNames[e.type] || e.type)} · ${esc(e.source)} · ${esc(e.severity)}</div>
            <div class="tl-title"><a href="#" onclick="Alerts.drilldown('${esc(e.project_id)}');return false;">${esc(e.project_id)}</a> — ${esc(e.title)}</div>
            <div class="tl-detail">${esc(e.detail)}</div>
          </div>`).join('')}
      </div>`;
  },
};
