/* GIS risk heatmap (Leaflet) */
const Gis = {
  map: null, layer: null,
  async render() {
    const el = document.getElementById('map');
    if (!this.map) {
      this.map = L.map('map').setView([26.4, 92.9], 7); // Assam
      L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; OpenStreetMap &copy; CARTO', maxZoom: 18,
      }).addTo(this.map);
      this.layer = L.layerGroup().addTo(this.map);
    }
    const data = await API.get('/api/map/projects');
    const colors = { Low: '#1e7d3c', Moderate: '#9a6c00', High: '#b85c08', Critical: '#b02330' };
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
        <a href="#" onclick="Alerts.drilldown('${esc(p.project_id)}');closeModal();return false;" style="color:#16468c">Open drill-down →</a>`);
    }
    if (!this._legend) {
      this._legend = L.control({ position: 'bottomright' });
      this._legend.onAdd = () => {
        const d = L.DomUtil.create('div');
        d.style.cssText = 'background:#ffffffee;padding:10px 12px;border-radius:6px;color:#1b2a44;font-size:12px;border:1px solid #c5d0e0;box-shadow:0 1px 4px rgba(20,40,80,.15)';
        d.innerHTML = '<b>Risk band</b><br>' + Object.entries(colors).map(([b, c]) =>
          `<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${c};margin-right:6px"></span>${b}`).join('<br>') +
          '<br><span style="color:#4e5f7d">circle size = risk score</span>';
        return d;
      };
      this._legend.addTo(this.map);
    }
  },
};
