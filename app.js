'use strict';

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const numberFormat = new Intl.NumberFormat();
const DEFAULT_MAPS = ['Tharsis', 'Hellas', 'Elysium', 'Vastitas Borealis'];
const SETTINGS_VERSION = 3;
const ELO_RANGES = {
  all: {min: 0, max: 0, label: 'All table Elo levels'},
  450: {min: 450, max: 0, label: '450+ average table Elo'},
  500: {min: 500, max: 0, label: '500+ average table Elo'},
  600: {min: 600, max: 0, label: '600+ average table Elo'},
};
const COMBINATION_TYPES = {
  'corp-prelude': {label:'Corp + Prelude', slot1:'Corporation', slot2:'Prelude', kind1:'corp', kind2:'prelude'},
  'corp-card': {label:'Corp + Card', slot1:'Corporation', slot2:'Card', kind1:'corp', kind2:'card'},
  'prelude-prelude': {label:'Prelude + Prelude', slot1:'Prelude 1', slot2:'Prelude 2', kind1:'prelude', kind2:'prelude'},
  'prelude-card': {label:'Prelude + Card', slot1:'Prelude', slot2:'Card', kind1:'prelude', kind2:'card'},
  'card-card': {label:'Card + Card', slot1:'Card 1', slot2:'Card 2', kind1:'card', kind2:'card'},
};
const DEFAULT_SETTINGS = {prelude: true, minAverageElo: 450, maxAverageElo: 0, maps: DEFAULT_MAPS, multiMap: false};
const MINIMUM_METRIC_OBSERVATIONS = 10;

let startingHands = [];
let combinations = [];
let startingSort = 'eloKept';
let startingDirection = 'desc';
let currentPage = 1;
let combinationPage = 1;
let combinationType = 'corp-prelude';
let combinationSort = 'totalLift';
let combinationDirection = 'desc';
let combinationRequestId = 0;
let keepCardsInView = false;
let lockedCardOrder = [];
let startingRequestId = 0;

function loadSettings() {
  try {
    const saved = typeof localStorage === 'undefined' ? {} : JSON.parse(localStorage.getItem('marsStatsSettings') || '{}');
    let maps = Array.isArray(saved.maps) ? saved.maps.filter(name => DEFAULT_MAPS.includes(name)) : DEFAULT_MAPS;
    const legacyDefault = maps.length === 3 && ['Tharsis', 'Hellas', 'Elysium'].every(name => maps.includes(name));
    if (saved.version !== SETTINGS_VERSION && legacyDefault) maps = DEFAULT_MAPS;
    const savedElo = Number(saved.minAverageElo ?? saved.minPlayerElo);
    const savedMaxElo = Number(saved.maxAverageElo ?? 0);
    const validRange = Object.values(ELO_RANGES).some(range => range.min === savedElo && range.max === savedMaxElo);
    const minAverageElo = validRange ? savedElo : 450;
    const maxAverageElo = validRange ? savedMaxElo : 0;
    return {prelude: saved.prelude !== false, minAverageElo, maxAverageElo, maps: maps.length ? maps : DEFAULT_MAPS, multiMap: saved.multiMap === true};
  } catch {
    return {...DEFAULT_SETTINGS, maps: [...DEFAULT_MAPS]};
  }
}

let settings = loadSettings();

function asNumber(value, fallback = 0) {
  const parsed = Number(value);
  return value !== null && value !== '' && Number.isFinite(parsed) ? parsed : fallback;
}

function nullableNumber(value) {
  const parsed = Number(value);
  return value !== null && value !== '' && Number.isFinite(parsed) ? parsed : null;
}

function safe(value) {
  return String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
}

function fmt(value) {
  return numberFormat.format(Math.round(asNumber(value)));
}

function signed(value, digits = 2) {
  const number = nullableNumber(value);
  if (number === null) return '—';
  const rounded = Math.abs(number) < 0.5 * (10 ** -digits) ? 0 : number;
  return `${rounded > 0 ? '+' : rounded < 0 ? '−' : ''}${Math.abs(rounded).toFixed(digits)}`;
}

function tone(value) {
  const number = nullableNumber(value);
  return number === null ? 'muted' : number >= 0 ? 'positive' : 'negative';
}

function metricWithMinimum(value, observations) {
  return asNumber(observations) >= MINIMUM_METRIC_OBSERVATIONS ? nullableNumber(value) : null;
}

function normalizeStartingPayload(payload) {
  const rows = Array.isArray(payload?.data) ? payload.data : [];
  return rows.map(row => {
    const offered = asNumber(row.offeredGames);
    const kept = asNumber(row.keptGames);
    const notKept = asNumber(row.notKeptGames);
    return {
      name: String(row.cardName ?? ''), offered, kept, notKept,
      keepRate: asNumber(row.keepRate),
      eloOffered: metricWithMinimum(row.avgEloGainOffered ?? row.avgEloDeltaOffered, offered),
      eloKept: metricWithMinimum(row.avgEloGainKept ?? row.avgEloDeltaKept, kept),
      eloNotKept: metricWithMinimum(row.avgEloGainNotKept ?? row.avgEloDeltaNotKept, notKept),
    };
  }).filter(row => row.name && row.offered > 0);
}

function normalizeCombinationPayload(payload) {
  const rows = Array.isArray(payload?.combinations) ? payload.combinations : [];
  return rows.map(row => ({
    name1: String(row.name1 ?? row.cardA ?? ''), name2: String(row.name2 ?? row.cardB ?? ''),
    gameCount: asNumber(row.gameCount ?? row.games),
    avgEloChange: nullableNumber(row.avgEloChange ?? row.avgEloGain ?? row.avgEloDelta),
    winRate: nullableNumber(row.winRate),
    baseline1Elo: nullableNumber(row.baseline1Elo), baseline2Elo: nullableNumber(row.baseline2Elo),
    lift1: nullableNumber(row.lift1), lift2: nullableNumber(row.lift2),
    totalLift: nullableNumber(row.totalLift ?? row.vsBaseline),
  })).filter(row => row.name1 && row.name2 && row.gameCount > 0);
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {headers:{Accept:'application/json'}, cache:'no-store', ...options});
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `${response.status} ${response.statusText}`);
  return payload;
}

function cohortQuery() {
  const query = new URLSearchParams({
    prelude: settings.prelude ? 'on' : 'off',
    maps: settings.maps.join(','),
    min_average_elo: String(settings.minAverageElo),
    max_average_elo: String(settings.maxAverageElo),
  });
  return query;
}

function startingQuery() {
  const query = cohortQuery();
  const draft = $('#startingDraftNumber').value.trim();
  query.set('stage', draft ? 'draft' : 'starting_hand');
  if (draft) query.set('draft_number', draft);
  return query;
}

function combinationQuery() {
  const query = cohortQuery();
  const config = COMBINATION_TYPES[combinationType];
  const generation = $('#combinationDraftNumber').value.trim();
  const usesCards = config.kind1 === 'card' || config.kind2 === 'card';
  query.set('combo_type', combinationType);
  query.set('stage', usesCards && generation ? 'draft' : 'starting_hand');
  if (usesCards && generation) query.set('draft_number', generation);
  return query;
}

function saveSettings() {
  if (typeof localStorage !== 'undefined') localStorage.setItem('marsStatsSettings', JSON.stringify({...settings, version: SETTINGS_VERSION}));
}

function selectedEloRange() {
  return Object.entries(ELO_RANGES).find(([, range]) => range.min === settings.minAverageElo && range.max === settings.maxAverageElo) || ['450', ELO_RANGES[450]];
}

function renderSettings() {
  $$('[data-map-filter]').forEach(button => {
    const selected = settings.maps.includes(button.dataset.mapFilter);
    button.classList.toggle('active', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
  $$('[data-multi-map-toggle]').forEach(button => {
    button.classList.toggle('active', settings.multiMap);
    button.setAttribute('aria-pressed', String(settings.multiMap));
  });
  $$('[data-all-maps]').forEach(button => {
    const selected = settings.maps.length === DEFAULT_MAPS.length;
    button.classList.toggle('active', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
  $$('[data-prelude-setting]').forEach(button => {
    const selected = (button.dataset.preludeSetting === 'on') === settings.prelude;
    button.classList.toggle('active', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
  $$('[data-elo-setting]').forEach(button => {
    const selected = button.dataset.eloSetting === selectedEloRange()[0];
    button.classList.toggle('active', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
  const summary = `${settings.prelude ? 'Prelude on' : 'Prelude off'} · ${selectedEloRange()[1].label} · ${settings.maps.join(', ')}`;
  $('#settingsSummary').textContent = summary;
  $('#startingCohortSummary').textContent = `2 players · ${summary} · Draft on · Colonies off`;
  $('#combinationCohortSummary').textContent = `2 players · ${summary} · Draft on · Colonies off`;
}

function applySettings(message) {
  saveSettings();
  renderSettings();
  $('#startingDetail').hidden = true;
  Promise.all([loadStartingHands(keepCardsInView), loadCombinations()]);
  if (message) toast(message);
}

function sourceDescription(source) {
  if (!source?.games) {
    const scan = source?.filesScanned ? ` · ${fmt(source.filesScanned)} files scanned · ${fmt(source.skippedSchema)} missing required fields` : '';
    return `No indexed local replay data${scan} · watching ${source?.sourceDir || 'data/parsed'}`;
  }
  const updated = source.updatedAt ? new Date(source.updatedAt).toLocaleString() : 'unknown update time';
  const skipped = source.skippedSchema ? ` · ${fmt(source.skippedSchema)} records missing required fields` : '';
  const dataset = source.dataset || 'Local replay database';
  return `${dataset} · ${fmt(source.games)} player-games · ${fmt(source.offers)} starting-hand offers${skipped} · updated ${updated}`;
}

function setStatus(element, messageElement, state, message) {
  element.className = `source-status ${state}`;
  messageElement.textContent = message;
}

function filteredStartingRows() {
  const search = $('#startingSearch').value.trim().toLocaleLowerCase();
  const rows = startingHands.filter(row => row.name.toLocaleLowerCase().includes(search));
  if (keepCardsInView && lockedCardOrder.length) {
    const positions = new Map(lockedCardOrder.map((name, index) => [name, index]));
    return rows.sort((left, right) => (positions.get(left.name) ?? Infinity) - (positions.get(right.name) ?? Infinity));
  }
  return rows.sort((left, right) => {
      const a = left[startingSort];
      const b = right[startingSort];
      let comparison;
      if (typeof a === 'string') comparison = a.localeCompare(b);
      else if (a === null && b === null) comparison = 0;
      else if (a === null) comparison = -1;
      else if (b === null) comparison = 1;
      else comparison = a - b;
      return startingDirection === 'asc' ? comparison : -comparison;
  });
}

function renderCardOrderLock() {
  const button = $('#keepCardsInView');
  button.classList.toggle('active', keepCardsInView);
  button.setAttribute('aria-pressed', String(keepCardsInView));
}

function captureCardOrder() {
  lockedCardOrder = filteredStartingRows().map(row => row.name);
}

function renderStartingHands() {
  const rows = filteredStartingRows();
  const pageSize = asNumber($('#rowsPerPage').value, 25);
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  currentPage = Math.min(currentPage, pages);
  const start = (currentPage - 1) * pageSize;
  const visible = rows.slice(start, start + pageSize);
  $('#startingShowing').textContent = rows.length ? `Showing ${start + 1}-${start + visible.length} of ${rows.length} cards` : 'Showing 0 cards';
  $('#pageNumber').textContent = `Page ${currentPage} of ${pages}`;
  $('#previousPage').disabled = currentPage <= 1;
  $('#nextPage').disabled = currentPage >= pages;
  $('#startingTable').innerHTML = visible.length ? visible.map(row => `
    <tr data-starting-card="${safe(row.name)}">
      <td><div class="card-name" tabindex="0" data-card-preview="true" data-card-name="${safe(row.name)}" data-card-kind="card" data-card-image="${safe(cardImage(row.name, 'card'))}"><img class="card-image-thumb" src="${safe(cardImage(row.name, 'card'))}" alt="" onerror="this.hidden=true" /><span>${safe(row.name)}</span></div></td>
      <td class="${tone(row.eloKept)}">${signed(row.eloKept)}</td>
      <td class="${tone(row.eloNotKept)}">${signed(row.eloNotKept)}</td>
      <td>${row.keepRate.toFixed(1)}%</td>
      <td class="muted">${fmt(row.offered)}</td>
      <td class="${tone(row.eloOffered)}">${signed(row.eloOffered)}</td>
    </tr>`).join('') : '<tr><td colspan="6" class="empty-cell">No local records match these filters.</td></tr>';

  $$('[data-start-sort]').forEach(button => {
    button.querySelector('span').textContent = button.dataset.startSort === startingSort ? (startingDirection === 'asc' ? '↑' : '↓') : '↕';
  });
}

async function selectStartingCard(name) {
  const row = startingHands.find(card => card.name === name);
  if (!row) return;
  $('#detailCardName').textContent = row.name;
  $('#detailOffered').textContent = fmt(row.offered);
  $('#detailKeepRate').textContent = `${row.keepRate.toFixed(1)}%`;
  $('#detailKept').textContent = fmt(row.kept);
  $('#detailPassed').textContent = fmt(row.notKept);
  $('#eloOffered').textContent = signed(row.eloOffered);
  $('#eloKept').textContent = signed(row.eloKept);
  $('#eloPassed').textContent = signed(row.eloNotKept);
  $('#startingDetail').hidden = false;
  $('#draftBreakdown').innerHTML = '<tr><td colspan="7" class="empty-cell">Loading local breakdown…</td></tr>';
  try {
    const query = cohortQuery();
    query.set('card', name);
    const payload = await fetchJson(`/api/card-breakdown?${query}`);
    $('#draftBreakdown').innerHTML = payload.data.length ? payload.data.map(item => {
      const eloKept = metricWithMinimum(item.eloKept, item.kept);
      const eloNotKept = metricWithMinimum(item.eloNotKept, item.notKept);
      const eloOffered = metricWithMinimum(item.eloOffered, item.offered);
      return `<tr><td>${item.stage === 'starting_hand' ? 'Starting hand' : 'Draft'}</td><td>${item.stage === 'draft' ? item.draftNumber : '—'}</td><td>${fmt(item.offered)}</td><td>${item.keepRate.toFixed(1)}%</td><td class="${tone(eloKept)}">${signed(eloKept)}</td><td class="${tone(eloNotKept)}">${signed(eloNotKept)}</td><td class="${tone(eloOffered)}">${signed(eloOffered)}</td></tr>`;
    }).join('') : '<tr><td colspan="7" class="empty-cell">No stage breakdown is available.</td></tr>';
  } catch (error) {
    $('#draftBreakdown').innerHTML = `<tr><td colspan="8" class="empty-cell">${safe(error.message)}</td></tr>`;
  }
}

function itemSlug(name) {
  return String(name).normalize('NFKD').toLocaleLowerCase()
    .replace(/['’]/g, '').replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
}

function cardImage(name, kind) {
  return `assets/cards/${kind}/${itemSlug(name)}.png`;
}

function combinationMetric(value) {
  return value === null ? '—' : signed(value);
}

function combinationPercent(value) {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`;
}

function compareCombinationRows(left, right) {
  const a = left[combinationSort];
  const b = right[combinationSort];
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  const comparison = typeof a === 'number' && typeof b === 'number'
    ? a - b
    : String(a).localeCompare(String(b));
  return combinationDirection === 'asc' ? comparison : -comparison;
}

function renderCombinationControls() {
  const config = COMBINATION_TYPES[combinationType];
  const usesCards = config.kind1 === 'card' || config.kind2 === 'card';
  $$('[data-combination-type]').forEach(button => {
    const selected = button.dataset.combinationType === combinationType;
    button.classList.toggle('active', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
  $('#combinationRankingTitle').textContent = `${config.label} Rankings`;
  $('#combinationSlot1FilterLabel').textContent = config.slot1;
  $('#combinationSlot2FilterLabel').textContent = config.slot2;
  $('#combinationSlot1Heading').textContent = config.slot1;
  $('#combinationSlot2Heading').textContent = config.slot2;
  $('#combinationLift1Heading').textContent = config.slot1;
  $('#combinationLift2Heading').textContent = config.slot2;
  $('#combinationSearch1').placeholder = `Search ${config.slot1.toLocaleLowerCase()}...`;
  $('#combinationSearch2').placeholder = `Search ${config.slot2.toLocaleLowerCase()}...`;
  $('#combinationDraftNumber').disabled = !usesCards;
  $('#combinationDraftNumber').placeholder = usesCards ? 'Starting hand' : 'Not used for this type';
  $('#combinationDraftNote').textContent = usesCards
    ? 'Leave empty for Starting Hand. A generation uses project cards bought after that generation’s draft, whether or not they were later played.'
    : 'Bought generation does not apply because this combination contains no project card.';
  $$('[data-combo-sort]').forEach(button => {
    const indicator = button.lastElementChild;
    if (indicator) indicator.textContent = button.dataset.comboSort === combinationSort
      ? (combinationDirection === 'asc' ? '↑' : '↓') : '↕';
  });
}

function renderCombinationItem(name, kind, baseline) {
  const image = cardImage(name, kind);
  const baselineText = baseline === null ? '' : ` <small>(${signed(baseline)})</small>`;
  return `<div class="combination-item" tabindex="0" data-card-preview="true" data-card-name="${safe(name)}" data-card-kind="${safe(kind)}" data-card-image="${safe(image)}"><img src="${safe(image)}" alt="" onerror="this.hidden=true" /><span>${safe(name)}${baselineText}</span></div>`;
}

function renderCombinations() {
  const config = COMBINATION_TYPES[combinationType];
  const search1 = $('#combinationSearch1').value.trim().toLocaleLowerCase();
  const search2 = $('#combinationSearch2').value.trim().toLocaleLowerCase();
  const rows = combinations
    .filter(row => row.name1.toLocaleLowerCase().includes(search1) && row.name2.toLocaleLowerCase().includes(search2))
    .sort(compareCombinationRows);
  const pageSize = asNumber($('#combinationRowsPerPage').value, 50);
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  combinationPage = Math.min(combinationPage, pages);
  const start = (combinationPage - 1) * pageSize;
  const visible = rows.slice(start, start + pageSize);
  $('#combinationShowing').textContent = rows.length ? `Showing ${start + 1}-${start + visible.length} of ${fmt(rows.length)} combinations` : 'Showing 0 combinations';
  $('#combinationPageNumber').textContent = `Page ${combinationPage} of ${pages}`;
  $('#previousCombinationPage').disabled = combinationPage <= 1;
  $('#nextCombinationPage').disabled = combinationPage >= pages;
  $('#combinationTable').innerHTML = visible.length ? visible.map(row => `
    <tr>
      <td>${renderCombinationItem(row.name1, config.kind1, row.baseline1Elo)}</td>
      <td>${renderCombinationItem(row.name2, config.kind2, row.baseline2Elo)}</td>
      <td class="muted">${fmt(row.gameCount)}</td>
      <td class="${tone(row.avgEloChange)}">${combinationMetric(row.avgEloChange)}</td>
      <td>${combinationPercent(row.winRate)}</td>
      <td class="${tone(row.lift1)}">${combinationMetric(row.lift1)}</td>
      <td class="${tone(row.lift2)}">${combinationMetric(row.lift2)}</td>
      <td class="${tone(row.totalLift)}">${combinationMetric(row.totalLift)}</td>
    </tr>`).join('') : '<tr><td colspan="8" class="empty-cell">No local combinations match these filters.</td></tr>';
  renderCombinationControls();
}

async function loadStartingHands(preserveCardView = false) {
  const requestId = ++startingRequestId;
  const previousPage = currentPage;
  setStatus($('#sourceStatus'), $('#sourceMessage'), 'loading', 'Querying the local Parquet database…');
  try {
    const payload = await fetchJson(`/api/starting-hands?${startingQuery()}`);
    if (requestId !== startingRequestId) return;
    startingHands = normalizeStartingPayload(payload);
    currentPage = preserveCardView ? previousPage : 1;
    renderStartingHands();
    setStatus($('#sourceStatus'), $('#sourceMessage'), payload.source.games ? 'ready' : 'error', sourceDescription(payload.source));
  } catch (error) {
    if (requestId !== startingRequestId) return;
    startingHands = [];
    renderStartingHands();
    setStatus($('#sourceStatus'), $('#sourceMessage'), 'error', `Local database query failed: ${error.message}`);
  }
}

async function loadCombinations() {
  const requestId = ++combinationRequestId;
  setStatus($('#combinationStatus'), $('#combinationMessage'), 'loading', 'Querying the local Parquet database…');
  try {
    const payload = await fetchJson(`/api/combinations?${combinationQuery()}`);
    if (requestId !== combinationRequestId) return;
    combinations = normalizeCombinationPayload(payload);
    combinationPage = 1;
    renderCombinations();
    setStatus($('#combinationStatus'), $('#combinationMessage'), payload.source.games ? 'ready' : 'error', sourceDescription(payload.source));
  } catch (error) {
    if (requestId !== combinationRequestId) return;
    combinations = [];
    renderCombinations();
    setStatus($('#combinationStatus'), $('#combinationMessage'), 'error', `Local database query failed: ${error.message}`);
  }
}

async function rebuildDatabase(button) {
  button.classList.add('busy');
  try {
    const payload = await fetchJson('/api/rebuild', {method:'POST'});
    await Promise.all([loadStartingHands(), loadCombinations()]);
    toast(`Indexed ${fmt(payload.source.games)} player-games and ${fmt(payload.source.offers)} offers`);
  } catch (error) {
    toast(`Rebuild failed: ${error.message}`);
  } finally {
    button.classList.remove('busy');
  }
}

function showPage(name, updateHash = true) {
  if (!document.querySelector(`[data-page="${name}"]`)) name = 'starting-hands';
  $$('.page').forEach(page => page.classList.toggle('active', page.dataset.page === name));
  $$('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.pageLink === name));
  if (updateHash) history.replaceState(null, '', `#${name}`);
  $('#sidebar').classList.remove('mobile-open');
  $('#sidebarScrim').classList.remove('show');
  window.scrollTo({top:0, behavior:'instant'});
}

function toast(message) {
  const element = $('#toast');
  element.textContent = message;
  element.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.remove('show'), 3200);
}

$$('[data-page-link]').forEach(button => button.addEventListener('click', () => showPage(button.dataset.pageLink)));
$('#collapseButton').addEventListener('click', () => $('#sidebar').classList.toggle('collapsed'));
$('#menuButton').addEventListener('click', () => { $('#sidebar').classList.add('mobile-open'); $('#sidebarScrim').classList.add('show'); });
$('#sidebarScrim').addEventListener('click', () => { $('#sidebar').classList.remove('mobile-open'); $('#sidebarScrim').classList.remove('show'); });
$('#refreshButton').addEventListener('click', event => rebuildDatabase(event.currentTarget));
$('#refreshCombinations').addEventListener('click', event => rebuildDatabase(event.currentTarget));
$('#startingSearch').addEventListener('input', () => { currentPage = 1; renderStartingHands(); });
$('#startingDraftNumber').addEventListener('input', () => loadStartingHands(keepCardsInView));
$$('[data-map-filter]').forEach(button => button.addEventListener('click', () => {
  const map = button.dataset.mapFilter;
  if (!settings.multiMap) {
    settings = {...settings, maps: [map]};
  } else if (settings.maps.includes(map)) {
    if (settings.maps.length === 1) return toast('Keep at least one map selected');
    settings = {...settings, maps: settings.maps.filter(name => name !== map)};
  } else {
    settings = {...settings, maps: DEFAULT_MAPS.filter(name => settings.maps.includes(name) || name === map)};
  }
  applySettings(`${map} ${settings.maps.includes(map) ? 'included' : 'excluded'}`);
}));
$$('[data-multi-map-toggle]').forEach(button => button.addEventListener('click', () => {
  settings = {...settings, multiMap: !settings.multiMap};
  applySettings(settings.multiMap ? 'Multiple-map selection enabled' : 'Single-map selection enabled');
}));
$$('[data-all-maps]').forEach(button => button.addEventListener('click', () => {
  settings = {...settings, maps: [...DEFAULT_MAPS]};
  applySettings('Using all maps');
}));
$('#rowsPerPage').addEventListener('change', () => { currentPage = 1; renderStartingHands(); });
$('#previousPage').addEventListener('click', () => { currentPage = Math.max(1, currentPage - 1); renderStartingHands(); });
$('#nextPage').addEventListener('click', () => { currentPage += 1; renderStartingHands(); });
$('#startingTableView').addEventListener('click', event => {
  const row = event.target.closest('[data-starting-card]');
  if (row) selectStartingCard(row.dataset.startingCard);
  const sortButton = event.target.closest('[data-start-sort]');
  if (!sortButton) return;
  if (keepCardsInView) {
    keepCardsInView = false;
    lockedCardOrder = [];
    renderCardOrderLock();
  }
  const key = sortButton.dataset.startSort;
  if (startingSort === key) startingDirection = startingDirection === 'asc' ? 'desc' : 'asc';
  else { startingSort = key; startingDirection = key === 'name' ? 'asc' : 'desc'; }
  currentPage = 1;
  renderStartingHands();
});
$('#keepCardsInView').addEventListener('click', () => {
  if (keepCardsInView) {
    keepCardsInView = false;
    lockedCardOrder = [];
    renderCardOrderLock();
    renderStartingHands();
    toast('Card order unlocked');
    return;
  }
  captureCardOrder();
  keepCardsInView = true;
  renderCardOrderLock();
  toast('Current card order locked for cohort comparisons');
});
['combinationSearch1','combinationSearch2'].forEach(id => $(`#${id}`).addEventListener('input', () => { combinationPage = 1; renderCombinations(); }));
$('#combinationDraftNumber').addEventListener('input', () => loadCombinations());
$$('[data-combination-type]').forEach(button => button.addEventListener('click', () => {
  combinationType = button.dataset.combinationType;
  combinationPage = 1;
  combinationSort = 'totalLift';
  combinationDirection = 'desc';
  $('#combinationSearch1').value = '';
  $('#combinationSearch2').value = '';
  renderCombinationControls();
  loadCombinations();
}));
$('#combinationRowsPerPage').addEventListener('change', () => { combinationPage = 1; renderCombinations(); });
$('#previousCombinationPage').addEventListener('click', () => { combinationPage = Math.max(1, combinationPage - 1); renderCombinations(); });
$('#nextCombinationPage').addEventListener('click', () => { combinationPage += 1; renderCombinations(); });
$('.combination-table thead').addEventListener('click', event => {
  const button = event.target.closest('[data-combo-sort]');
  if (!button) return;
  const key = button.dataset.comboSort;
  if (combinationSort === key) combinationDirection = combinationDirection === 'asc' ? 'desc' : 'asc';
  else { combinationSort = key; combinationDirection = key.startsWith('name') ? 'asc' : 'desc'; }
  combinationPage = 1;
  renderCombinations();
});

function showCardPreview(target) {
  const preview = $('#cardPreview');
  const image = $('#cardPreviewImage');
  const rect = target.getBoundingClientRect();
  image.src = target.dataset.cardImage;
  image.alt = target.dataset.cardName;
  $('#cardPreviewName').textContent = target.dataset.cardName;
  $('#cardPreviewKind').textContent = target.dataset.cardKind === 'corp' ? 'Corporation' : target.dataset.cardKind === 'prelude' ? 'Prelude' : 'Project Card';
  preview.hidden = false;
  const width = 230;
  const left = rect.right + width + 24 <= window.innerWidth ? rect.right + 12 : Math.max(8, rect.left - width - 12);
  preview.style.left = `${left}px`;
  preview.style.top = `${Math.max(8, Math.min(rect.top - 70, window.innerHeight - 360))}px`;
}

function hideCardPreview() {
  $('#cardPreview').hidden = true;
}

['startingTable', 'combinationTable'].forEach(id => {
  const table = $(`#${id}`);
  table.addEventListener('mouseover', event => {
    const target = event.target.closest('[data-card-preview]');
    if (target) showCardPreview(target);
  });
  table.addEventListener('mouseout', event => {
    const target = event.target.closest('[data-card-preview]');
    if (target && !target.contains(event.relatedTarget)) hideCardPreview();
  });
  table.addEventListener('focusin', event => {
    const target = event.target.closest('[data-card-preview]');
    if (target) showCardPreview(target);
  });
  table.addEventListener('focusout', hideCardPreview);
});
$('#cardPreviewImage').addEventListener('error', hideCardPreview);
$$('[data-prelude-setting]').forEach(button => button.addEventListener('click', () => {
  settings = {...settings, prelude: button.dataset.preludeSetting === 'on'};
  applySettings(settings.prelude ? 'Using Prelude-on games' : 'Using Prelude-off games');
}));
$$('[data-elo-setting]').forEach(button => button.addEventListener('click', () => {
  const range = ELO_RANGES[button.dataset.eloSetting];
  settings = {...settings, minAverageElo: range.min, maxAverageElo: range.max};
  applySettings(`Using ${range.label}`);
}));
$('#resetSettings').addEventListener('click', () => {
  settings = {...DEFAULT_SETTINGS, maps: [...DEFAULT_MAPS]};
  applySettings('Competitive defaults restored');
});

window.__marsStatsTest = {normalizeStartingPayload, normalizeCombinationPayload, metricWithMinimum, signed};
renderSettings();
renderCardOrderLock();
renderCombinationControls();
showPage(location.hash.slice(1) || 'starting-hands', false);
loadStartingHands();
loadCombinations();
