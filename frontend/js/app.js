/* App shell: tab router + boot */
const TABS = {
  dashboard: Dashboard, alerts: Alerts, map: Gis, fundflow: FundFlow,
  duplicates: Duplicates, compliance: Compliance, upload: Upload,
  feedback: FeedbackTab, about: About,
};

function switchTab(name) {
  document.querySelectorAll('.tabs button').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
  document.getElementById('tab-' + name).classList.remove('hidden');
  const mod = TABS[name];
  if (mod) mod.render();
  if (name === 'map' && Gis.map) setTimeout(() => Gis.map.invalidateSize(), 60);
}

document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => switchTab(b.dataset.tab));

(async function boot() {
  const dateEl = document.getElementById('header-date');
  if (dateEl) {
    dateEl.textContent = new Date().toLocaleDateString('en-IN',
      { day: '2-digit', month: 'short', year: 'numeric' });
  }
  try {
    await API.get('/api/health');   // silent on success
  } catch {
    const el = document.getElementById('system-health');
    if (el) el.innerHTML = '<span class="health-offline">● service offline</span>';
  }
  switchTab('dashboard');
})();
