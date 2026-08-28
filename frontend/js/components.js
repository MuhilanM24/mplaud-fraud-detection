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

/* SVG semicircular risk gauge — animated arc + count-up number */
function riskGauge(score, band, size = 190) {
  const pct = Math.max(0, Math.min(100, +score || 0));
  const colors = { Low: '#15803d', Moderate: '#a16207', High: '#c2410c', Critical: '#b91c1c' };
  const color = colors[band] || '#1d4ed8';
  const d = 'M 30 88 A 70 70 0 0 1 170 88';   // semicircle, left -> over the top -> right
  return `
  <div class="gauge">
    <svg viewBox="0 0 200 112" width="${size}" height="${size * 0.56}" role="img" aria-label="risk ${pct} of 100">
      <path d="${d}" stroke="#e9edf3" stroke-width="13" fill="none" stroke-linecap="round"/>
      <path class="gauge-arc" d="${d}" stroke="${color}" stroke-width="13" fill="none"
            stroke-linecap="round" pathLength="100" data-pct="${pct}"
            style="stroke-dasharray:0 100"/>
      <text class="gauge-num" x="100" y="80" text-anchor="middle" data-target="${(+score) || 0}">0.0</text>
      <text class="gauge-band" x="100" y="102" text-anchor="middle" fill="${color}">${esc(band || '')}</text>
    </svg>
    <div class="gauge-label">Risk score 0–100</div>
  </div>`;
}

/* Kick gauge animations inside a freshly rendered container (e.g. a modal). */
function animateGauges(root) {
  (root || document).querySelectorAll('.gauge-arc').forEach((el) => {
    // double rAF so the browser paints the 0-state before transitioning
    requestAnimationFrame(() => requestAnimationFrame(() => {
      el.style.strokeDasharray = `${el.dataset.pct} 100`;
    }));
  });
  (root || document).querySelectorAll('.gauge-num').forEach((el) => {
    const target = parseFloat(el.dataset.target) || 0;
    const t0 = performance.now(), dur = 1000;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur);
      const e = 1 - Math.pow(1 - k, 3);           // ease-out cubic
      el.textContent = (target * e).toFixed(1);
      if (k < 1) requestAnimationFrame(step);
      else el.textContent = target.toFixed(1);
    };
    requestAnimationFrame(step);
  });
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
        <div style="position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;background:rgba(0,0,0,.18)"></div>
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
  animateGauges(root);
  return root;
}
function closeModal() { document.getElementById('modal-root').innerHTML = ''; }

const spinner = (label = 'Loading') => `<span><span class="spinner"></span>${esc(label)}…</span>`;
