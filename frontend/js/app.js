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
  try {
    await API.get('/api/health');
    document.getElementById('system-health').innerHTML =
      '<span class="dot"></span>API online · demo dataset loaded';
  } catch {
    document.getElementById('system-health').innerHTML =
      '<span class="dot" style="background:var(--critical)"></span>API offline';
  }
  switchTab('dashboard');
})();
