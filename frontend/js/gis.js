/* GIS risk heatmap (Leaflet) */
const Gis = {
  map: null, layer: null,
  async render() {
    const el = document.getElementById('map');
    if (!this.map) {
      this.map = L.map('map').setView([26.4, 92.9], 7); // Assam
      L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; OpenStreetMap &copy; CARTO', maxZoom: 18,
      }).addTo(this.map);
      this.layer = L.layerGroup().addTo(this.map);
    }
    const data = await API.get('/api/map/projects');
    const colors = { Low: '#2fbf71', Moderate: '#e2b93b', High: '#ef8c3a', Critical: '#e5484d' };
    this.layer.clearLayers();
    for (const p of data.projects) {
      if (p.lat == null || p.lon == null) continue;
      L.circleMarker([p.lat, p.lon], {
        radius: 5 + (p.risk / 100) * 11,
        color: colors[p.band], fillColor: colors[p.band],
        fillOpacity: 0.45, weight: 1.2,
      }).addTo(this.layer).bindPopup(`
        <b>${esc(p.project_id)}</b> ${bandChip(p.band)}<br>
        ${esc(p.desc || '')}<br>
        Risk score <b>${p.risk}</b> · ${esc(p.district || '')}<br>
        <a href="#" onclick="Alerts.drilldown('${esc(p.project_id)}');closeModal();return false;" style="color:#7fb0ff">Open drill-down →</a>`);
    }
    if (!this._legend) {
      this._legend = L.control({ position: 'bottomright' });
      this._legend.onAdd = () => {
        const d = L.DomUtil.create('div');
        d.style.cssText = 'background:#14203aee;padding:10px 12px;border-radius:10px;color:#e6edf7;font-size:12px;border:1px solid #24365c';
        d.innerHTML = '<b>Risk band</b><br>' + Object.entries(colors).map(([b, c]) =>
          `<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${c};margin-right:6px"></span>${b}`).join('<br>') +
          '<br><span style="color:#93a5c4">circle size = risk score</span>';
        return d;
      };
      this._legend.addTo(this.map);
    }
  },
};
