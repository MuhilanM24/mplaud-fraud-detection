/* Duplicate-work detection tab */
const Duplicates = {
  async render() {
    const el = document.getElementById('tab-duplicates');
    el.innerHTML = spinner('Comparing work descriptions');
    const d = await API.get('/api/duplicates');
    el.innerHTML = `
      <div class="note-banner">
        <b>Duplicate-work detection.</b> NLP semantic similarity over work descriptions + DBSCAN geospatial clustering
        (≤ 1.5 km) — flags two "different" sanctioned works that are likely the same physical asset claimed twice.
        <br><b>Active NLP backend:</b> ${esc(d.backend)} · similarity threshold ${d.sim_threshold} · proximity ${d.distance_km} km.
        ${d.backend.includes('TF-IDF') ? '<br><span style="color:var(--moderate)">⚠ Offline fallback backend in use (sentence-transformers model not cached). Similarity scoring is less rigorous than true sentence embeddings; flagged pairs still require human confirmation.</span>' : ''}
      </div>
      ${d.pairs.length ? `
      <div class="table-wrap"><table>
        <thead><tr><th>Similarity</th><th>Distance</th><th>District</th><th>Work A</th><th>Work B</th><th>MP A / MP B</th><th></th></tr></thead>
        <tbody>${d.pairs.map(p => `
          <tr>
            <td><b>${p.similarity}</b></td><td>${p.distance_km} km</td><td>${esc(p.district || '—')}</td>
            <td class="wrap"><span class="mono">${esc(p.project_id_a)}</span><br>${esc(p.description_a)}</td>
            <td class="wrap"><span class="mono">${esc(p.project_id_b)}</span><br>${esc(p.description_b)}</td>
            <td class="wrap">${esc(p.mp_a || '—')}<br>${esc(p.mp_b || '—')}</td>
            <td><button class="btn small secondary" onclick="Alerts.drilldown('${esc(p.project_id_a)}')">Open A</button>
                <button class="btn small secondary" onclick="Alerts.drilldown('${esc(p.project_id_b)}')">Open B</button></td>
          </tr>`).join('')}
        </tbody></table></div>`
      : callout('info', 'No duplicate pairs detected', 'No near-duplicate descriptions within geo-proximity were found in this dataset.')}`;
  },
};
