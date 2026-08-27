/* Shared UI components */
const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const fmtINR = (v) => {
  if (v == null || isNaN(+v)) return '—';
  v = +v;
  if (v >= 1e5) return `Rs ${(v / 1e5).toFixed(1)}L`;
  return `Rs ${Math.round(v).toLocaleString('en-IN')}`;
};

function bandChip(band) { return `<span class="band-chip band-${esc(band)}">${esc(band)}</span>`; }
function scorePill(score, band) { return `<span class="score-pill score-${esc(band)}">${(+score).toFixed(1)}</span>`; }

/* SVG semicircular risk gauge */
function riskGauge(score, band, size = 190) {
  const pct = Math.max(0, Math.min(100, +score || 0));
  const colors = { Low: '#2fbf71', Moderate: '#e2b93b', High: '#ef8c3a', Critical: '#e5484d' };
  const color = colors[band] || '#4f8cff';
  const r = 70, cx = 100, cy = 90;
  const arc = (from, to, c) => {
    const a1 = Math.PI * (1 + from / 100), a2 = Math.PI * (1 + to / 100);
    const x1 = cx + r * Math.cos(a1), y1 = cy - r * Math.sin(a1);
    const x2 = cx + r * Math.cos(a2), y2 = cy - r * Math.sin(a2);
    return `<path d="M ${x1} ${y1} A ${r} ${r} 0 0 1 ${x2} ${y2}" stroke="${c}" stroke-width="14" fill="none" stroke-linecap="round"/>`;
  };
  return `
  <div>
    <svg viewBox="0 0 200 110" width="${size}" height="${size * 0.58}">
      ${arc(0, 100, '#1c2b4d')}
      ${arc(0, pct, color)}
      <text x="100" y="82" text-anchor="middle" font-size="34" font-weight="800" fill="#fff">${(+score).toFixed(1)}</text>
      <text x="100" y="100" text-anchor="middle" font-size="11" fill="${color}" letter-spacing="1.5">${esc(band ? band.toUpperCase() : '')}</text>
    </svg>
    <div class="gauge-label hint">Risk score 0–100 · routed to human review</div>
  </div>`;
}

/* Explainability factor bars (SHAP or deviation ranking) */
function factorBars(factors) {
  if (!factors || !factors.length) return '<div class="hint">No factor attribution available.</div>';
  const maxAbs = Math.max(...factors.map(f => Math.abs(f.shap_value ?? f.z_score ?? 0)), 1e-6);
  return factors.map(f => {
    const val = f.shap_value ?? f.z_score ?? 0;
    const w = Math.abs(val) / maxAbs * 50;
    const up = f.direction === 'increases_risk';
    return `
    <div class="factor">
      <div>
        <div>${esc(f.label || f.feature)}</div>
        <div class="hint">${esc(f.hint || '')}</div>
      </div>
      <div class="bar-bg">
        <div class="bar ${up ? 'up' : 'down'}" style="${up ? 'left:50%' : 'right:50%'}; width:${w}%"></div>
        <div style="position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;background:#ffffff22"></div>
      </div>
      <div class="${up ? 'dir-up' : 'dir-down'}">${up ? '▲ raises' : '▼ lowers'}<div class="hint mono">${f.shap_value != null ? f.shap_value.toFixed(2) : 'z=' + f.z_score} · value ${f.feature_value ?? '—'}</div></div>
    </div>`;
  }).join('');
}

function statusLine(flagged, status) {
  return flagged
    ? `<span class="status-flag">● ${esc(status || 'Flagged for investigation')}</span>`
    : `<span class="status-ok">● ${esc(status || 'Not flagged')}</span>`;
}

function callout(kind, title, detail) {
  return `<div class="callout ${kind}"><b>${esc(title)}</b><br>${esc(detail)}</div>`;
}

function modal(html) {
  const root = document.getElementById('modal-root');
  root.innerHTML = `<div class="modal-backdrop"><div class="modal">${html}</div></div>`;
  root.querySelector('.modal-backdrop').addEventListener('click', (e) => {
    if (e.target === root.querySelector('.modal-backdrop')) closeModal();
  });
  return root;
}
function closeModal() { document.getElementById('modal-root').innerHTML = ''; }

const spinner = (label = 'Loading') => `<span><span class="spinner"></span>${esc(label)}…</span>`;
