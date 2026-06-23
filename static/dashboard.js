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
  refreshDashboardView();
}

navMapBtn.addEventListener('click', showMap);
navDashboardBtn.addEventListener('click', showDashboard);

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
    showDashboardDefault();
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
  if(selectedDashStation) renderStationDashboard(selectedDashStation);
  else renderDashboardDefault();
}

function showDashboardDefault(){
  document.getElementById('dashboardDefault').style.display = 'block';
  document.getElementById('dashboardResults').style.display = 'none';
  renderDashboardDefault();
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

  document.getElementById('dashboardDefault').style.display = areas.length ? 'none' : 'block';
  document.getElementById('dashboardResults').style.display = areas.length ? 'block' : 'none';
  if(!areas.length){ renderDashboardDefault(); return; }

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
