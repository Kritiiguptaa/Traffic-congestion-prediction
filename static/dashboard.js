// ---- navigation: Map / Dashboard ----
const navMapBtn = document.getElementById('navMapBtn');
const navDashboardBtn = document.getElementById('navDashboardBtn');
const mapView = document.getElementById('mapView');
const dashboardView = document.getElementById('dashboardView');
let currentView = 'map';

function showMap(){
  currentView = 'map';
  mapView.style.display = 'block';
  dashboardView.style.display = 'none';
  navMapBtn.classList.add('active');
  navDashboardBtn.classList.remove('active');
  map.invalidateSize();
}

function showDashboard(){
  currentView = 'dashboard';
  mapView.style.display = 'none';
  dashboardView.style.display = 'block';
  navMapBtn.classList.remove('active');
  navDashboardBtn.classList.add('active');
  showDashHub();            // always land on the hub
  refreshDashboardView();   // populate every section's containers
}

navMapBtn.addEventListener('click', showMap);
navDashboardBtn.addEventListener('click', showDashboard);

// ---- hub-and-spoke navigation: hub landing <-> focused sections ----
const dashHub = document.getElementById('dashHub');
const dashSections = {
  impact:    document.getElementById('sectionImpact'),
  patrol:    document.getElementById('sectionPatrol'),
  analytics: document.getElementById('sectionAnalytics'),
  stations:  document.getElementById('sectionStations'),
};

function showDashHub(){
  if(dashHub) dashHub.style.display = 'block';
  Object.values(dashSections).forEach(s => { if(s) s.style.display = 'none'; });
  if(dashboardView) dashboardView.scrollTop = 0;
}

function showDashSection(name){
  if(dashHub) dashHub.style.display = 'none';
  Object.entries(dashSections).forEach(([k, s]) => { if(s) s.style.display = (k === name) ? 'block' : 'none'; });
  if(dashboardView) dashboardView.scrollTop = 0;
  if(name === 'patrol') renderPatrolPlan();  // ensure latest plan when opened
}

[...document.querySelectorAll('.hub-tile')].forEach(tile => {
  tile.addEventListener('click', () => showDashSection(tile.dataset.section));
});
[...document.querySelectorAll('.dash-back')].forEach(btn => {
  btn.addEventListener('click', showDashHub);
});

function formatHour(h){
  if(h === null || h === undefined) return '—';
  const period = h >= 12 ? 'PM' : 'AM';
  let hr = h % 12; if(hr === 0) hr = 12;
  return `${hr} ${period}`;
}

function trendArrow(label){
  if(label === 'rising') return '▲';
  if(label === 'falling') return '▼';
  return '▬';
}

// ---- dashboard: searchable police-station dropdown ----
const dashStationSearch = document.getElementById('dashStationSearch');
const dashStationSuggestions = document.getElementById('dashStationSuggestions');
let selectedDashStation = null;

dashStationSearch.addEventListener('input', () => {
  const q = dashStationSearch.value.trim().toLowerCase();
  if(!q){
    dashStationSuggestions.style.display = 'none';
    selectedDashStation = null;
    showStationsDefault();
    return;
  }
  const stationNames = [...new Set(allClusters.map(c => c.police_station).filter(Boolean))];
  const matches = stationNames.filter(s => s.toLowerCase().includes(q)).sort().slice(0, 8);
  renderDashSuggestions(matches);
});

function renderDashSuggestions(matches){
  if(!matches.length){ dashStationSuggestions.style.display = 'none'; return; }
  dashStationSuggestions.innerHTML = matches.map(s => `<div class="suggestion-item">${s}</div>`).join('');
  dashStationSuggestions.style.display = 'block';
  [...dashStationSuggestions.querySelectorAll('.suggestion-item')].forEach((el, i) => {
    el.addEventListener('click', () => {
      selectedDashStation = matches[i];
      dashStationSearch.value = selectedDashStation;
      dashStationSuggestions.style.display = 'none';
      renderStationDashboard(selectedDashStation);
    });
  });
}

document.addEventListener('click', (e) => {
  if(!e.target.closest('.dash-station-search-wrap')) dashStationSuggestions.style.display = 'none';
});

function refreshDashboardView(){
  if(currentView !== 'dashboard') return;
  renderDashboardDefault();                                  // hub + impact + analytics + patrol + busiest stations
  if(selectedDashStation) renderStationDashboard(selectedDashStation);  // station drilldown if one is active
}

// reset the Stations section back to its default (busiest-stations) view
function showStationsDefault(){
  document.getElementById('stationsDefault').style.display = 'block';
  document.getElementById('dashboardResults').style.display = 'none';
}

function renderDashboardDefault(){
  if(!allClusters.length) return;

  const totalViolations = allClusters.reduce((sum, a) => sum + a.violations, 0);
  const stationCount = new Set(allClusters.map(c => c.police_station).filter(Boolean)).size;
  const highRiskCount = allClusters.filter(a => riskLabel(a.predicted_score) === 'high').length;

  document.getElementById('cityStatAreas').textContent = allClusters.length;
  document.getElementById('cityStatViolations').textContent = totalViolations;
  document.getElementById('cityStatHighRisk').textContent = highRiskCount;
  document.getElementById('cityStatStations').textContent = stationCount;

  // NEW: headline banner — quick "why this matters" framing for judges
  renderDashHeadline(allClusters, totalViolations, highRiskCount);
  // NEW: quadrant visual (frequency x severity)
  renderQuadrantGrid(allClusters);
  // NEW: traffic-flow impact — ranked chokepoints + explainability feature card
  renderTopChokepoints();
  // NEW: predictive patrol deployment plan (scheduled by shift via the temporal model)
  renderPatrolPlan();

  // hub tile mini-stats
  const maxTfi = Math.max(0, ...allClusters.map(c => c.tfi_index || 0));
  const setTile = (id, txt) => { const el = document.getElementById(id); if(el) el.textContent = txt; };
  setTile('tileImpactStat', `Worst chokepoint: TFI ${maxTfi}/100`);
  setTile('tileAnalyticsStat', `${allClusters.length} hotspots analysed`);
  setTile('tileStationsStat', `${stationCount} stations covered`);

  // top priority areas, citywide
  const top = allClusters.slice().sort((a, b) => b.predicted_score - a.predicted_score).slice(0, 5);
  const topMaxScore = Math.max(...top.map(a => a.predicted_score), 0.001);

  document.getElementById('topAreasList').innerHTML = top.map(a => {
    const pct = Math.max(6, Math.round((a.predicted_score / topMaxScore) * 100));
    return `
      <div class="dash-bar-row dash-bar-row-clickable">
        <div class="dash-bar-row-top">
          <span class="dash-bar-label">${a.location || a.junction_name || a.police_station}</span>
          <span class="risk-pill risk-${riskLabel(a.predicted_score)}">${riskLabel(a.predicted_score)}</span>
        </div>
        <div class="dash-bar-track">
          <div class="dash-bar-fill" style="width:${pct}%;"></div>
        </div>
        <div class="dash-bar-meta">
          Impact <b>${a.predicted_score}</b> &middot; <b>${a.police_station}</b> &middot; ${a.violations} violations &middot;
          Peak <b>${a.peak_dow_name || '—'} ~${formatHour(a.peak_hour)}</b> ${trendSpark(a.trend_label, a.trend_pct)}
        </div>
      </div>
    `;
  }).join('');

  [...document.querySelectorAll('#topAreasList .dash-bar-row')].forEach((el, i) => {
    el.addEventListener('click', () => {
      const a = top[i];
      selectedLocation = { lat: a.latitude, lng: a.longitude, label: a.location || a.police_station };
      searchInput.value = selectedLocation.label;
      showMap();
      map.flyTo([a.latitude, a.longitude], 16, { duration: 0.6 });
      runPrediction();
    });
  });

  // citywide risk breakdown
  const counts = { high: 0, medium: 0, low: 0 };
  allClusters.forEach(a => counts[riskLabel(a.predicted_score)]++);
  const total = allClusters.length || 1;
  const riskRows = [
    { key: 'high', label: 'High risk', varName: '--high' },
    { key: 'medium', label: 'Medium risk', varName: '--medium' },
    { key: 'low', label: 'Low risk', varName: '--low' },
  ];

  document.getElementById('riskBreakdownChart').innerHTML = riskRows.map(r => {
    const count = counts[r.key];
    const pct = Math.round((count / total) * 100);
    return `
      <div class="dash-risk-row">
        <div class="dash-risk-row-top">
          <span class="dash-risk-label">${r.label}</span>
          <span class="dash-risk-count">${count} areas &middot; ${pct}%</span>
        </div>
        <div class="dash-bar-track">
          <div class="dash-bar-fill" style="width:${Math.max(pct, 2)}%;background:var(${r.varName});"></div>
        </div>
      </div>
    `;
  }).join('');

  // most congested areas, citywide (by raw violation count, not impact score)
  const congested = allClusters.slice().sort((a, b) => b.violations - a.violations).slice(0, 5);
  const maxViolations = Math.max(...congested.map(a => a.violations), 1);

  document.getElementById('topCongestedList').innerHTML = congested.map(a => {
    const pct = Math.max(6, Math.round((a.violations / maxViolations) * 100));
    return `
      <div class="dash-bar-row dash-bar-row-clickable">
        <div class="dash-bar-row-top">
          <span class="dash-bar-label">${a.location || a.junction_name || a.police_station}</span>
          <span class="risk-pill risk-${riskLabel(a.predicted_score)}">${riskLabel(a.predicted_score)}</span>
        </div>
        <div class="dash-bar-track">
          <div class="dash-bar-fill" style="width:${pct}%;"></div>
        </div>
        <div class="dash-bar-meta">
          <b>${a.violations}</b> violations &middot; <b>${a.police_station}</b> &middot;
          Impact <b>${a.predicted_score}</b> &middot; Peak <b>${a.peak_dow_name || '—'} ~${formatHour(a.peak_hour)}</b> ${trendSpark(a.trend_label, a.trend_pct)}
        </div>
      </div>
    `;
  }).join('');

  [...document.querySelectorAll('#topCongestedList .dash-bar-row')].forEach((el, i) => {
    el.addEventListener('click', () => {
      const a = congested[i];
      selectedLocation = { lat: a.latitude, lng: a.longitude, label: a.location || a.police_station };
      searchInput.value = selectedLocation.label;
      showMap();
      map.flyTo([a.latitude, a.longitude], 16, { duration: 0.6 });
      runPrediction();
    });
  });

  // trend overview, citywide
  const trendCounts = { rising: 0, falling: 0, stable: 0 };
  allClusters.forEach(a => { trendCounts[a.trend_label || 'stable']++; });
  const trendRows = [
    { key: 'rising', label: 'Rising', varName: '--high' },
    { key: 'falling', label: 'Falling', varName: '--low' },
    { key: 'stable', label: 'Stable', varName: '--bar' },
  ];

  document.getElementById('trendOverviewChart').innerHTML = trendRows.map(r => {
    const count = trendCounts[r.key];
    const pct = Math.round((count / total) * 100);
    return `
      <div class="dash-risk-row">
        <div class="dash-risk-row-top">
          <span class="dash-risk-label">${r.label}</span>
          <span class="dash-risk-count">${count} areas &middot; ${pct}%</span>
        </div>
        <div class="dash-bar-track">
          <div class="dash-bar-fill" style="width:${Math.max(pct, 2)}%;background:var(${r.varName});"></div>
        </div>
      </div>
    `;
  }).join('');

  // busiest police stations, citywide (aggregated across their areas)
  const byStation = {};
  allClusters.forEach(a => {
    if(!a.police_station) return;
    if(!byStation[a.police_station]) byStation[a.police_station] = { violations: 0, areas: 0, impactSum: 0 };
    byStation[a.police_station].violations += a.violations;
    byStation[a.police_station].areas += 1;
    byStation[a.police_station].impactSum += a.predicted_score;
  });
  const stationRows = Object.entries(byStation)
    .map(([name, s]) => ({ name, ...s, avgImpact: s.impactSum / s.areas }))
    .sort((a, b) => b.violations - a.violations)
    .slice(0, 5);
  const maxStationViolations = Math.max(...stationRows.map(s => s.violations), 1);

  document.getElementById('topStationsList').innerHTML = stationRows.map(s => {
    const pct = Math.max(6, Math.round((s.violations / maxStationViolations) * 100));
    return `
      <div class="dash-bar-row">
        <div class="dash-bar-row-top">
          <span class="dash-bar-label">${s.name}</span>
          <span class="dash-bar-meta">${s.areas} areas</span>
        </div>
        <div class="dash-bar-track">
          <div class="dash-bar-fill" style="width:${pct}%;"></div>
        </div>
        <div class="dash-bar-meta">
          <b>${s.violations}</b> violations &middot; Avg impact <b>${s.avgImpact.toFixed(3)}</b>
        </div>
      </div>
    `;
  }).join('');
}

function renderStationDashboard(station){
  const areas = allClusters
    .filter(c => c.police_station === station)
    .slice()
    .sort((a, b) => b.predicted_score - a.predicted_score);

  document.getElementById('stationsDefault').style.display = areas.length ? 'none' : 'block';
  document.getElementById('dashboardResults').style.display = areas.length ? 'block' : 'none';
  if(!areas.length){ return; }

  document.getElementById('dashStationName').textContent = station;

  const totalViolations = areas.reduce((sum, a) => sum + a.violations, 0);
  const highRisk = areas.filter(a => riskLabel(a.predicted_score) === 'high').length;
  const rising = areas.filter(a => a.trend_label === 'rising').length;

  document.getElementById('statAreas').textContent = areas.length;
  document.getElementById('statViolations').textContent = totalViolations;
  document.getElementById('statHighRisk').textContent = highRisk;
  document.getElementById('statRising').textContent = rising;

  const maxScore = Math.max(...areas.map(a => a.predicted_score), 0.001);

  document.getElementById('dashAreaList').innerHTML = areas.map((a, i) => {
    const pct = Math.max(6, Math.round((a.predicted_score / maxScore) * 100));
    return `
      <div class="dash-bar-row">
        <div class="dash-bar-row-top">
          <span class="dash-bar-label">${a.location || a.junction_name || station}</span>
          <span class="risk-pill risk-${riskLabel(a.predicted_score)}">${riskLabel(a.predicted_score)}</span>
        </div>
        <div class="dash-bar-track">
          <div class="dash-bar-fill" style="width:${pct}%;"></div>
        </div>
        <div class="dash-bar-meta">
          Impact <b>${a.predicted_score}</b> &middot; ${a.violations} violations &middot;
          Peak <b>${a.peak_dow_name || '—'} ~${formatHour(a.peak_hour)}</b> &middot;
          <span class="trend-${a.trend_label}">${trendArrow(a.trend_label)} ${a.trend_label}</span>
          (${a.trend_pct > 0 ? '+' : ''}${a.trend_pct}%) ${trendSpark(a.trend_label, a.trend_pct)} &middot; ${a.quadrant || '—'} &middot;
          <a href="#" class="dash-view-link" data-idx="${i}">View on map</a>
        </div>
      </div>
    `;
  }).join('');

  [...document.querySelectorAll('.dash-view-link')].forEach(el => {
    el.addEventListener('click', (e) => {
      e.preventDefault();
      const a = areas[Number(el.dataset.idx)];
      selectedLocation = { lat: a.latitude, lng: a.longitude, label: a.location || a.police_station };
      searchInput.value = selectedLocation.label;
      showMap();
      map.flyTo([a.latitude, a.longitude], 16, { duration: 0.6 });
      runPrediction();
    });
  });
}

// ==========================================================================
// NEW (hackathon polish pass): headline banner, time filters, patrol report
// export, quadrant visual, trend sparklines. Nothing above this point was
// removed — only extended (see trendSpark()/renderDashHeadline() call-outs).
// ==========================================================================

// ---- NEW: headline stat banner ----
function renderDashHeadline(clusters, totalViolations, highRiskCount){
  const el = document.getElementById('dashHeadline');
  if(!el) return;

  const sorted = clusters.slice().sort((a, b) => b.violations - a.violations);
  const top10 = sorted.slice(0, 10);
  const top10Violations = top10.reduce((s, a) => s + a.violations, 0);
  const concentrationPct = totalViolations > 0 ? Math.round((top10Violations / totalViolations) * 100) : 0;
  const risingCount = clusters.filter(c => c.trend_label === 'rising').length;

  el.innerHTML = `
    <div class="dash-headline-item">
      <span class="dash-headline-value">${highRiskCount} high-risk zones</span>
      <span class="dash-headline-label">out of ${clusters.length} tracked areas</span>
    </div>
    <div class="dash-headline-item">
      <span class="dash-headline-value">${concentrationPct}% of violations</span>
      <span class="dash-headline-label">concentrated in just the top 10 areas</span>
    </div>
    <div class="dash-headline-item">
      <span class="dash-headline-value">${risingCount} areas trending up</span>
      <span class="dash-headline-label">worth proactive patrol attention</span>
    </div>
  `;
}

// ---- NEW: time filter chips — quick presets that set timeInput + reload ----
const dashTimeFiltersEl = document.getElementById('dashTimeFilters');
if(dashTimeFiltersEl){
  dashTimeFiltersEl.addEventListener('click', async (e) => {
    const btn = e.target.closest('.dash-time-chip');
    if(!btn) return;
    [...dashTimeFiltersEl.querySelectorAll('.dash-time-chip')].forEach(c => c.classList.remove('active'));
    btn.classList.add('active');

    const preset = btn.dataset.when;
    const now = new Date();

    if(preset === 'now'){
      now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
      timeInput.value = now.toISOString().slice(0, 16);
    } else if(preset === 'today-peak'){
      // use 9 AM today as a representative morning-peak slot
      now.setHours(9, 0, 0, 0);
      now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
      timeInput.value = now.toISOString().slice(0, 16);
    } else if(preset === 'weekend-night'){
      // next Saturday, 9 PM
      const day = now.getDay();
      const daysUntilSat = (6 - day + 7) % 7;
      now.setDate(now.getDate() + daysUntilSat);
      now.setHours(21, 0, 0, 0);
      now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
      timeInput.value = now.toISOString().slice(0, 16);
    } else if(preset === 'all'){
      timeInput.value = '';
    }

    await loadClusters();
    if(selectedLocation) runPrediction();
    refreshDashboardView();
  });
}

// ---- NEW: quadrant visual (Frequent/Rare x Severe/Mild) ----
function renderQuadrantGrid(clusters){
  const grid = document.getElementById('quadrantGrid');
  if(!grid) return;

  const counts = {
    'Frequent & Severe': 0,
    'Frequent & Mild': 0,
    'Rare & Severe': 0,
    'Rare & Mild': 0,
  };
  clusters.forEach(c => { if(counts[c.quadrant] !== undefined) counts[c.quadrant]++; });

  const cells = [
    { key: 'Frequent & Severe', cls: 'quadrant-fs', hint: 'steady patrol priority' },
    { key: 'Frequent & Mild', cls: 'quadrant-fm', hint: 'routine monitoring' },
    { key: 'Rare & Severe', cls: 'quadrant-rs', hint: 'one-off incident watch' },
    { key: 'Rare & Mild', cls: 'quadrant-rm', hint: 'low priority' },
  ];

  grid.innerHTML = cells.map(c => `
    <div class="quadrant-cell ${c.cls}">
      <span class="quadrant-cell-label">${c.key}</span>
      <span class="quadrant-cell-count">${counts[c.key]}</span>
      <span class="quadrant-cell-label">${c.hint}</span>
    </div>
  `).join('');
}

// ---- NEW: trend mini sparkline (visual stand-in for arrow+pct) ----
function trendSpark(label, pct){
  // 4 bars approximating a trend line: rising = ascending heights, falling = descending, stable = flat
  let heights;
  if(label === 'rising') heights = [4, 7, 10, 14];
  else if(label === 'falling') heights = [14, 10, 7, 4];
  else heights = [8, 8, 8, 8];

  const bars = heights.map(h => `<span class="trend-spark-bar" style="height:${h}px;"></span>`).join('');
  return `<span class="trend-spark" title="${label} (${pct > 0 ? '+' : ''}${pct}%)">${bars}</span>`;
}

// ---- NEW: Generate Patrol Report (text export) ----
function buildPatrolReportText(){
  const now = new Date();
  const top = allClusters.slice().sort((a, b) => b.predicted_score - a.predicted_score).slice(0, 5);

  let lines = [];
  lines.push('BENGALURU PARKING HOTSPOTS — PATROL PRIORITY REPORT');
  lines.push(`Generated: ${now.toLocaleString()}`);
  lines.push('');
  lines.push(`Total tracked areas: ${allClusters.length}`);
  lines.push(`High-risk areas: ${allClusters.filter(a => riskLabel(a.predicted_score) === 'high').length}`);
  lines.push('');
  lines.push('TOP 5 PRIORITY AREAS');
  lines.push('---------------------');
  top.forEach((a, i) => {
    lines.push(`${i + 1}. ${a.location || a.junction_name || a.police_station}`);
    lines.push(`   Police station : ${a.police_station}`);
    lines.push(`   Risk level     : ${riskLabel(a.predicted_score)} (impact ${a.predicted_score})`);
    lines.push(`   Violations     : ${a.violations}`);
    lines.push(`   Peak time      : ${a.peak_dow_name || '—'} ~${formatHour(a.peak_hour)}`);
    lines.push(`   Trend          : ${a.trend_label} (${a.trend_pct > 0 ? '+' : ''}${a.trend_pct}%)`);
    lines.push(`   Quadrant       : ${a.quadrant || '—'}`);
    lines.push('');
  });
  return lines.join('\n');
}

const generateReportBtn = document.getElementById('generateReportBtn');
if(generateReportBtn){
  generateReportBtn.addEventListener('click', () => {
    const text = buildPatrolReportText();
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `patrol-report-${new Date().toISOString().slice(0, 10)}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  });
}

// ==========================================================================
// NEW: Traffic-flow impact — quantifies how much each hotspot chokes the
// carriageway, and explains the score (component breakdown + assumptions).
// ==========================================================================

// ---- ranked list of worst chokepoints by Traffic-Flow Impact ----
function renderTopChokepoints(){
  const listEl = document.getElementById('topChokepointsList');
  if(!listEl) return;

  const ranked = allClusters.slice()
    .filter(c => c.tfi_index !== undefined)
    .sort((a, b) => b.tfi_index - a.tfi_index);

  if(!ranked.length){ listEl.innerHTML = '<div class="dash-bar-meta">No impact data available.</div>'; return; }

  const top = ranked.slice(0, 6);
  listEl.innerHTML = top.map((a, i) => {
    const pct = Math.max(6, a.tfi_index);
    return `
      <div class="dash-bar-row dash-bar-row-clickable" data-cid="${a.cluster_id}">
        <div class="dash-bar-row-top">
          <span class="dash-bar-label">${a.location || a.junction_name || a.police_station}</span>
          <span class="tfi-pill">TFI ${a.tfi_index}</span>
        </div>
        <div class="dash-bar-track">
          <div class="dash-bar-fill" style="width:${pct}%;background:var(--high);"></div>
        </div>
        <div class="dash-bar-meta">
          ~<b>${a.pct_lane_capacity_cut}%</b> lane cut &middot; ~<b>${a.veh_affected_peak}</b> veh/hr delayed at peak &middot;
          <b>${a.police_station}</b> &middot; mostly ${a.block_reason || '—'}
        </div>
      </div>
    `;
  }).join('');

  [...listEl.querySelectorAll('.dash-bar-row')].forEach((el, i) => {
    el.addEventListener('click', () => renderImpactFeature(top[i]));
  });

  // default the explainability card to the #1 chokepoint
  renderImpactFeature(ranked[0]);
}

// ---- explainability feature card for a single hotspot ----
function renderImpactFeature(c){
  if(!c || c.tfi_index === undefined) return;

  document.getElementById('impactName').textContent =
    c.location || c.junction_name || c.police_station || 'Selected hotspot';

  const junctionPct = Math.round((c.junction_share || 0) * 100);
  const junctionTxt = junctionPct >= 25
    ? ` and <b>${junctionPct}%</b> of incidents sit at a junction (where blockage backs up far more traffic)`
    : '';

  document.getElementById('impactSentence').innerHTML =
    `Mostly <b>${c.block_reason || 'mixed parking violations'}</b>${junctionTxt}. ` +
    `This hotspot blocks an estimated <b>${c.pct_lane_capacity_cut}%</b> of one lane's capacity, ` +
    `delaying roughly <b>${c.veh_affected_peak}</b> vehicles per peak hour ` +
    `(peak <b>${c.peak_dow_name || '—'} ~${formatHour(c.peak_hour)}</b>).`;

  document.getElementById('impactTfi').textContent = c.tfi_index;
  document.getElementById('impactLaneCut').textContent = `${c.pct_lane_capacity_cut}%`;
  document.getElementById('impactVeh').textContent = `~${c.veh_affected_peak}`;

  // component breakdown bars (each 0..1 -> %)
  const footprintFrac = Math.min(1, (c.mean_footprint || 1) / 2.2);
  const rows = [
    { label: 'Obstruction severity', frac: c.obstruction_intensity || 0,
      val: `${Math.round((c.obstruction_intensity || 0) * 100)}%` },
    { label: 'At a junction', frac: c.junction_share || 0,
      val: `${junctionPct}%` },
    { label: 'Vehicle footprint', frac: footprintFrac,
      val: `${(c.mean_footprint || 1).toFixed(1)}× car` },
    { label: 'Volume / persistence', frac: c.volume_factor || 0,
      val: `${c.violations} incidents` },
  ];

  document.getElementById('impactBreakdown').innerHTML = rows.map(r => `
    <div class="impact-bar-row">
      <div class="impact-bar-top">
        <span class="impact-bar-label">${r.label}</span>
        <span class="impact-bar-val">${r.val}</span>
      </div>
      <div class="impact-bar-track">
        <div class="impact-bar-fill" style="width:${Math.max(3, Math.round(r.frac * 100))}%;"></div>
      </div>
    </div>
  `).join('');

  document.getElementById('impactAssumptions').innerHTML =
    'Estimate assumes ~1,500 veh/hr per lane at peak, with obstruction weighted by ' +
    'violation type — a double-parked truck at a junction ≈ a full lane block, a helmet ' +
    'violation ≈ none. TFI index is relative across all tracked hotspots.';
}

// ==========================================================================
// NEW: Predictive patrol deployment plan — uses the temporal model to forecast
// which zones will be worst at each enforcement shift, turning reactive
// patrolling into a scheduled, proactive roster.
// ==========================================================================

const PATROL_SHIFTS = [
  { name: 'Morning peak', hour: 8 },
  { name: 'Midday',       hour: 13 },
  { name: 'Evening peak', hour: 18 },
  { name: 'Night',        hour: 21 },
];
const PATROL_TOP_N = 4;
let patrolPlanDay = 0;            // 0 = today, 1 = tomorrow
let patrolPlanCache = {};        // keyed by date string
let lastPatrolPlan = null;       // for the download button

function patrolPlanDateStr(dayOffset){
  const d = new Date();
  d.setDate(d.getDate() + dayOffset);
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 10);
}

async function renderPatrolPlan(){
  const body = document.getElementById('patrolPlanBody');
  if(!body) return;

  const dateStr = patrolPlanDateStr(patrolPlanDay);
  if(patrolPlanCache[dateStr]){
    drawPatrolPlan(patrolPlanCache[dateStr], dateStr);
    return;
  }

  body.innerHTML = '<div class="dash-bar-meta">Forecasting hotspots for each shift…</div>';

  try {
    // query the temporal model in parallel, once per shift hour
    const results = await Promise.all(PATROL_SHIFTS.map(s => {
      const when = `${dateStr}T${String(s.hour).padStart(2, '0')}:00`;
      return fetch(`${API}/api/clusters?when=${encodeURIComponent(when)}`)
        .then(r => r.json())
        .then(d => ({ shift: s, clusters: d.clusters || [] }));
    }));

    const plan = results.map(({ shift, clusters }) => {
      const ranked = clusters.slice().sort((a, b) => b.predicted_score - a.predicted_score);
      // spread patrols: prefer distinct police stations, then fill
      const chosen = [], seen = new Set();
      for(const c of ranked){
        if(chosen.length >= PATROL_TOP_N) break;
        const st = c.police_station || c.cluster_id;
        if(seen.has(st)) continue;
        seen.add(st);
        chosen.push(c);
      }
      for(const c of ranked){
        if(chosen.length >= PATROL_TOP_N) break;
        if(!chosen.includes(c)) chosen.push(c);
      }
      return { shift, zones: chosen };
    });

    patrolPlanCache[dateStr] = plan;
    drawPatrolPlan(plan, dateStr);
  } catch(err){
    body.innerHTML = '<div class="dash-bar-meta">Could not generate plan (is the server running?).</div>';
  }
}

function drawPatrolPlan(plan, dateStr){
  const body = document.getElementById('patrolPlanBody');
  lastPatrolPlan = { plan, dateStr };

  body.innerHTML = `<div class="patrol-grid">` + plan.map(({ shift, zones }) => `
    <div class="patrol-shift">
      <div class="patrol-shift-head">
        <span class="patrol-shift-name">${shift.name}</span>
        <span class="patrol-shift-time">${String(shift.hour).padStart(2, '0')}:00</span>
      </div>
      ${zones.map((z, i) => `
        <div class="patrol-zone" data-lat="${z.latitude}" data-lng="${z.longitude}" data-label="${(z.location || z.police_station || '').replace(/"/g, '')}">
          <div class="patrol-zone-top">
            <span class="patrol-zone-name">${z.location || z.junction_name || z.police_station}</span>
            <span class="risk-pill risk-${riskLabel(z.predicted_score)}">${riskLabel(z.predicted_score)}</span>
          </div>
          <div class="patrol-zone-meta">
            <span class="patrol-rank">${i + 1}</span>
            ${z.police_station} &middot; impact <b>${z.predicted_score}</b>
            ${z.tfi_index !== undefined ? `&middot; TFI ${z.tfi_index}` : ''}
          </div>
        </div>
      `).join('')}
    </div>
  `).join('') + `</div>`;

  // click a zone -> jump to it on the map
  [...body.querySelectorAll('.patrol-zone')].forEach(el => {
    el.addEventListener('click', () => {
      const lat = parseFloat(el.dataset.lat), lng = parseFloat(el.dataset.lng);
      selectedLocation = { lat, lng, label: el.dataset.label };
      searchInput.value = el.dataset.label;
      showMap();
      map.flyTo([lat, lng], 16, { duration: 0.6 });
      runPrediction();
    });
  });
}

function buildPatrolPlanText(){
  if(!lastPatrolPlan) return '';
  const { plan, dateStr } = lastPatrolPlan;
  let lines = [];
  lines.push('BENGALURU — PREDICTIVE PATROL DEPLOYMENT PLAN');
  lines.push(`For: ${dateStr}  (forecast by temporal model, per enforcement shift)`);
  lines.push('');
  plan.forEach(({ shift, zones }) => {
    lines.push(`${shift.name.toUpperCase()} — ${String(shift.hour).padStart(2, '0')}:00`);
    lines.push('-'.repeat(40));
    zones.forEach((z, i) => {
      lines.push(`  ${i + 1}. ${z.location || z.junction_name || z.police_station}`);
      lines.push(`     Station   : ${z.police_station}`);
      lines.push(`     Predicted : ${riskLabel(z.predicted_score)} (impact ${z.predicted_score}${z.tfi_index !== undefined ? `, TFI ${z.tfi_index}` : ''})`);
      lines.push(`     Reason    : ${z.block_reason || '—'}`);
    });
    lines.push('');
  });
  return lines.join('\n');
}

// day toggle (Today / Tomorrow)
const planDayToggle = document.getElementById('planDayToggle');
if(planDayToggle){
  planDayToggle.addEventListener('click', (e) => {
    const btn = e.target.closest('.plan-day-btn');
    if(!btn) return;
    [...planDayToggle.querySelectorAll('.plan-day-btn')].forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    patrolPlanDay = Number(btn.dataset.day);
    renderPatrolPlan();
  });
}

// download deployment plan
const downloadPlanBtn = document.getElementById('downloadPlanBtn');
if(downloadPlanBtn){
  downloadPlanBtn.addEventListener('click', () => {
    const text = buildPatrolPlanText();
    if(!text) return;
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `patrol-deployment-${lastPatrolPlan ? lastPatrolPlan.dateStr : 'plan'}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  });
}
