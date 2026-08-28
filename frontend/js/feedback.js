/* Feedback log tab — human-in-the-loop labelled data */
const FeedbackTab = {
  async render() {
    const el = document.getElementById('tab-feedback');
    el.innerHTML = spinner('Loading feedback');
    const d = await API.get('/api/feedback');
    const verdictChip = (v) => v === 'confirmed' ? '<span class="band-chip band-Critical">confirmed</span>'
      : v === 'false_positive' ? '<span class="band-chip band-Low">false positive</span>'
      : '<span class="band-chip band-Moderate">needs more info</span>';
    el.innerHTML = `
      <div class="note-banner">
        <b>Human-in-the-loop feedback.</b> Investigators mark alerts as confirmed / false positive / needs more info.
        Every record is captured as labelled training data (project features + score + verdict) for future model
        retraining — the feedback-capture mechanism is in scope; automated retraining is not.
      </div>
      <a class="btn secondary" style="text-decoration:none;display:inline-block;padding:8px 14px;margin-bottom:12px"
         href="/api/feedback/export.csv">⬇ Export labelled data (CSV)</a>
      ${d.feedback.length ? `
      <div class="table-wrap"><table>
        <thead><tr><th>When</th><th>Project</th><th>Dataset</th><th>Verdict</th><th>Score</th><th>Investigator</th><th>Note</th></tr></thead>
        <tbody>${d.feedback.map(f => `
          <tr><td>${esc((f.created_at || '').slice(0, 19).replace('T', ' '))}</td>
          <td class="mono">${esc(f.project_id)}</td><td>${esc(f.dataset_id)}</td>
          <td>${verdictChip(f.verdict)}</td><td>${f.risk_score ?? '—'}</td>
          <td>${esc(f.investigator || '—')}</td><td class="wrap">${esc(f.note || '')}</td></tr>`).join('')}
        </tbody></table></div>`
      : callout('info', 'No feedback yet', 'Open any project in the Alert Center and record an investigator verdict to populate this log.')}`;
  },
};
