'use strict';

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const numberFormat = new Intl.NumberFormat();
const DEFAULT_MAPS = ['Tharsis', 'Hellas', 'Elysium', 'Vastitas Borealis'];
const SETTINGS_VERSION = 4;
const VIEW_VERSION = 3;
const ELO_RANGES = {
  all: {min: 0, max: 0, label: 'All table Elo levels'},
  450: {min: 450, max: 0, label: '450+ average table Elo'},
  500: {min: 500, max: 0, label: '500+ average table Elo'},
  600: {min: 600, max: 0, label: '600+ average table Elo'},
};
const COMBINATION_TYPES = {
  'corp-prelude': {label:'Corp + Prelude', slot1:'Corporation', slot2:'Prelude', kind1:'corp', kind2:'prelude'},
  'corp-card': {label:'Corp + Card', slot1:'Corporation', slot2:'Card', kind1:'corp', kind2:'card'},
  corporations: {label:'Corporations', slot1:'Corporation', slot2:'', kind1:'corp', standalone:true},
  'prelude-prelude': {label:'Prelude + Prelude', slot1:'Prelude 1', slot2:'Prelude 2', kind1:'prelude', kind2:'prelude'},
  'prelude-card': {label:'Prelude + Card', slot1:'Prelude', slot2:'Card', kind1:'prelude', kind2:'card'},
  'card-card': {label:'Card + Card', slot1:'Card 1', slot2:'Card 2', kind1:'card', kind2:'card'},
};
const DEFAULT_SETTINGS = {prelude: true, minAverageElo: 450, maxAverageElo: 0, maps: DEFAULT_MAPS, multiMap: false};
const MINIMUM_METRIC_OBSERVATIONS = 100;
const COMBINATION_SORTS = ['name1', 'name2', 'gameCount', 'keepRate', 'avgEloChange', 'avgEloNotKept', 'winRate', 'lift1', 'lift2', 'totalLift'];
const PAGE_SIZES = [10, 25, 50, 100];

function positiveInteger(value, fallback = 1) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function generationValue(value) {
  const text = String(value ?? '').trim();
  return text === '' ? '' : String(positiveInteger(text, 0) || '');
}

function draftGenerationValue(value) {
  const text = String(value ?? '').trim();
  if (!text) return '';
  const generation = Number(generationValue(text));
  return Number.isInteger(generation) && generation >= 2 && generation <= 14 ? String(generation) : '';
}

function playGenerationValue(value) {
  const normalized = playGenerationInputValue(value);
  return normalized ? Number(normalized) : 1;
}

function playGenerationInputValue(value) {
  const text = String(value ?? '').trim();
  if (!text) return '';
  const generation = Number(text);
  return Number.isInteger(generation) && generation >= 1 && generation <= 14 ? String(generation) : '';
}

function normalizeViewState(saved = {}) {
  const combinationSortValue = COMBINATION_SORTS.includes(saved.combinationSort) ? saved.combinationSort : 'totalLift';
  const type = Object.hasOwn(COMBINATION_TYPES, saved.combinationType) ? saved.combinationType : 'corp-card';
  const corpMode = saved.corpCardMode === 'played' ? 'played' : 'draft';
  return {
    combinationGeneration: Object.hasOwn(saved, 'combinationGeneration')
      ? (corpMode === 'played' ? playGenerationInputValue(saved.combinationGeneration) : draftGenerationValue(saved.combinationGeneration)) : '',
    combinationSearch1: String(saved.combinationSearch1 ?? ''),
    combinationSearch2: String(saved.combinationSearch2 ?? ''),
    combinationSearch3: String(saved.combinationSearch3 ?? ''),
    combinationSearch4: String(saved.combinationSearch4 ?? ''),
    combinationSearch5: String(saved.combinationSearch5 ?? ''),
    combinationRows: PAGE_SIZES.includes(Number(saved.combinationRows)) ? Number(saved.combinationRows) : 25,
    combinationMinimumGames: generationValue(saved.combinationMinimumGames),
    combinationType: type,
    combinationSort: saved.combinationSort ? combinationSortValue : 'avgEloChange',
    combinationDirection: saved.combinationDirection === 'asc' ? 'asc' : 'desc',
    combinationPage: positiveInteger(saved.combinationPage),
    corpCardMode: corpMode,
    adjustCorporationElo: saved.adjustCorporationElo === true,
    selectedDetailCard: String(saved.selectedDetailCard ?? ''),
    selectedDetailCorporation: String(saved.selectedDetailCorporation ?? ''),
  };
}

function loadViewState() {
  try {
    const saved = typeof localStorage === 'undefined' ? {} : JSON.parse(localStorage.getItem('marsStatsView') || '{}');
    const queryType = typeof location === 'undefined' ? '' : new URLSearchParams(location.search).get('combination') || '';
    const state = saved.version === VIEW_VERSION ? saved : {};
    return normalizeViewState(Object.hasOwn(COMBINATION_TYPES, queryType) ? {...state, combinationType: queryType} : state);
  } catch {
    return normalizeViewState();
  }
}

const initialView = loadViewState();

let combinations = [];
let playedRows = [];
let combinationPage = initialView.combinationPage;
let combinationType = initialView.combinationType;
let combinationSort = initialView.combinationSort;
let combinationDirection = initialView.combinationDirection;
const combinationSearchMemory = {};
const initialCombinationConfig = COMBINATION_TYPES[initialView.combinationType];
combinationSearchMemory[initialCombinationConfig.kind1] = initialView.combinationSearch1;
combinationSearchMemory[initialCombinationConfig.kind2] = initialView.combinationSearch2;
let combinationRequestId = 0;
let cardDetailRequestId = 0;
let combinationsLoaded = false;
let directRankingMode = false;
let corpCardMode = initialView.corpCardMode;
let adjustCorporationElo = initialView.adjustCorporationElo;
let selectedDetailCard = initialView.selectedDetailCard;
let selectedDetailCorporation = initialView.selectedDetailCorporation;

function loadSettings() {
  try {
    const saved = typeof localStorage === 'undefined' ? {} : JSON.parse(localStorage.getItem('marsStatsSettings') || '{}');
    const currentSettings = saved.version === SETTINGS_VERSION;
    const maps = currentSettings && Array.isArray(saved.maps)
      ? saved.maps.filter(name => DEFAULT_MAPS.includes(name)) : [...DEFAULT_MAPS];
    const savedElo = Number(saved.minAverageElo ?? saved.minPlayerElo);
    const savedMaxElo = Number(saved.maxAverageElo ?? 0);
    const validRange = Object.values(ELO_RANGES).some(range => range.min === savedElo && range.max === savedMaxElo);
    const minAverageElo = validRange ? savedElo : 450;
    const maxAverageElo = validRange ? savedMaxElo : 0;
    return {prelude: saved.prelude !== false, minAverageElo, maxAverageElo, maps: maps.length ? maps : DEFAULT_MAPS, multiMap: currentSettings && saved.multiMap === true};
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

function normalizedSearchText(value) {
  return String(value ?? '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
    .toLocaleLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

function fuzzySearchMatches(value, query) {
  const words = normalizedSearchText(value).split(/\s+/).filter(Boolean);
  const tokens = normalizedSearchText(query).split(/\s+/).filter(Boolean);
  let wordIndex = 0;
  return tokens.every(token => {
    for (; wordIndex < words.length; wordIndex += 1) {
      const word = words[wordIndex];
      let characterIndex = 0;
      for (const character of token) {
        characterIndex = word.indexOf(character, characterIndex);
        if (characterIndex === -1) break;
        characterIndex += 1;
      }
      if (characterIndex !== -1) {
        wordIndex += 1;
        return true;
      }
    }
    return false;
  });
}

function filterRowsBySearch(rows, valueForRow, query) {
  const normalizedQuery = normalizedSearchText(query);
  if (!normalizedQuery) return rows;
  const hasExactMatch = rows.some(row => normalizedSearchText(valueForRow(row)) === normalizedQuery);
  return rows.filter(row => hasExactMatch
    ? normalizedSearchText(valueForRow(row)) === normalizedQuery
    : fuzzySearchMatches(valueForRow(row), query));
}

function filterRowsByAnySearch(rows, valueForRow, queries) {
  const activeQueries = queries.map(query => String(query ?? '').trim()).filter(Boolean);
  if (!activeQueries.length) return rows;
  const matches = new Set();
  activeQueries.forEach(query => filterRowsBySearch(rows, valueForRow, query).forEach(row => matches.add(row)));
  return rows.filter(row => matches.has(row));
}

function filterRowsByOrderedSearch(rows, valueForRow, queries) {
  const activeQueries = queries.map(query => String(query ?? '').trim()).filter(Boolean);
  if (!activeQueries.length) return rows;
  const seen = new Set();
  const ordered = [];
  activeQueries.forEach(query => {
    filterRowsBySearch(rows, valueForRow, query).forEach(row => {
      if (seen.has(row)) return;
      seen.add(row);
      ordered.push(row);
    });
  });
  return ordered;
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

function requestedMetricMinimum() {
  return positiveInteger($('#combinationMinimumGames')?.value, MINIMUM_METRIC_OBSERVATIONS);
}

function metricForDisplay(value, observations) {
  return asNumber(observations) >= requestedMetricMinimum() ? nullableNumber(value) : null;
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
      winRate: nullableNumber(row.winRateKept ?? row.winRate),
      eloOffered: nullableNumber(row.avgEloGainOffered ?? row.avgEloDeltaOffered),
      eloKept: nullableNumber(row.avgEloGainKept ?? row.avgEloDeltaKept),
      eloNotKept: nullableNumber(row.avgEloGainNotKept ?? row.avgEloDeltaNotKept),
    };
  }).filter(row => row.name && row.offered > 0);
}

function normalizeCombinationPayload(payload) {
  const rows = Array.isArray(payload?.combinations) ? payload.combinations : [];
  return rows.map(row => ({
    name1: String(row.name1 ?? row.cardA ?? ''), name2: String(row.name2 ?? row.cardB ?? ''),
    gameCount: asNumber(row.gameCount ?? row.games),
    offeredGames: asNumber(row.offeredGames ?? row.gameCount ?? row.games),
    keepRate: nullableNumber(row.keepRate),
    notKeptGames: asNumber(row.notKeptGames),
    avgEloChange: nullableNumber(row.avgEloChange ?? row.avgEloGain ?? row.avgEloDelta),
    avgEloNotKept: nullableNumber(row.avgEloNotKept),
    corporationBaselineElo: nullableNumber(row.corporationBaselineElo),
    winRate: nullableNumber(row.winRate),
    baseline1Elo: nullableNumber(row.baseline1Elo), baseline2Elo: nullableNumber(row.baseline2Elo),
    notKept1Elo: nullableNumber(row.notKept1Elo), notKept2Elo: nullableNumber(row.notKept2Elo),
    lift1: nullableNumber(row.lift1), lift2: nullableNumber(row.lift2),
    totalLift: nullableNumber(row.totalLift ?? row.vsBaseline),
  })).filter(row => row.name1 && row.name2 && row.offeredGames > 0);
}

function normalizeCardOnlyPayload(payload) {
  return normalizeStartingPayload(payload).map(row => ({
    name1: '', name2: row.name,
    gameCount: row.kept, offeredGames: row.offered, keepRate: row.keepRate / 100, notKeptGames: row.notKept,
    avgEloChange: row.eloKept, avgEloNotKept: row.eloNotKept,
    // Starting-hand API win rates are already percentages; combination rows use 0–1.
    winRate: row.winRate === null ? null : row.winRate / 100,
    baseline1Elo: null, baseline2Elo: null,
    lift1: null, lift2: null, totalLift: null,
  }));
}

function normalizeStandalonePayload(payload) {
  const rows = Array.isArray(payload?.items) ? payload.items : [];
  return rows.map(row => ({
    name1: '', name2: String(row.name ?? ''), gameCount: asNumber(row.gameCount), offeredGames: asNumber(row.offeredGames ?? row.gameCount), keepRate: nullableNumber(row.keepRate),
    notKeptGames: asNumber(row.notKeptGames), avgEloChange: nullableNumber(row.avgEloChange), avgEloNotKept: nullableNumber(row.avgEloNotKept),
    winRate: nullableNumber(row.winRate), baseline1Elo: null, baseline2Elo: null,
    lift1: null, lift2: null, totalLift: null,
  })).filter(row => row.name2 && row.gameCount > 0);
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

function cardOnlyQuery() {
  const query = cohortQuery();
  const draft = draftGenerationValue($('#combinationDraftNumber').value);
  query.set('stage', draft ? 'draft' : 'starting_hand');
  if (draft) query.set('draft_number', draft);
  query.set('smooth', '1');
  return query;
}

function combinationQuery() {
  const query = cohortQuery();
  const config = COMBINATION_TYPES[combinationType];
  const generation = $('#combinationDraftNumber').value.trim();
  const usesCards = config.kind1 === 'card' || config.kind2 === 'card';
  query.set('combo_type', combinationType);
  const draft = usesCards ? draftGenerationValue(generation) : '';
  query.set('stage', draft ? 'draft' : 'starting_hand');
  if (draft) query.set('draft_number', draft);
  if (usesCards) query.set('smooth', '1');
  return query;
}

function standaloneQuery(kind) {
  const query = cohortQuery();
  query.set('kind', kind);
  return query;
}

function saveSettings() {
  if (typeof localStorage !== 'undefined') localStorage.setItem('marsStatsSettings', JSON.stringify({...settings, version: SETTINGS_VERSION}));
}

function saveViewState() {
  if (typeof localStorage === 'undefined') return;
  localStorage.setItem('marsStatsView', JSON.stringify({
    version: VIEW_VERSION,
    combinationGeneration: $('#combinationDraftNumber').value,
    combinationSearch1: $('#combinationSearch1').value,
    combinationSearch2: $('#combinationSearch2').value,
    combinationSearch3: $('#combinationSearch3').value,
    combinationSearch4: $('#combinationSearch4').value,
    combinationSearch5: $('#combinationSearch5').value,
    combinationMinimumGames: $('#combinationMinimumGames').value,
    combinationRows: Number($('#combinationRowsPerPage').value),
    combinationType, combinationSort, combinationDirection, combinationPage,
    corpCardMode, adjustCorporationElo, selectedDetailCard, selectedDetailCorporation,
  }));
}

function restoreViewState() {
  $('#combinationDraftNumber').value = initialView.combinationGeneration;
  $('#combinationSearch1').value = initialView.combinationSearch1;
  $('#combinationSearch2').value = initialView.combinationSearch2;
  $('#combinationSearch3').value = initialView.combinationSearch3;
  $('#combinationSearch4').value = initialView.combinationSearch4;
  $('#combinationSearch5').value = initialView.combinationSearch5;
  $('#combinationMinimumGames').value = initialView.combinationMinimumGames;
  $('#combinationRowsPerPage').value = String(initialView.combinationRows);
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
  $('#combinationCohortSummary').textContent = `2 players · ${summary} · Draft on · Colonies off`;
}

function applySettings(message) {
  saveSettings();
  renderSettings();
  if ($('[data-page="gen1-production"]').classList.contains('active')) loadGen1Production();
  else if (combinationsLoaded) loadCombinations();
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

function offeredGameCount(row) {
  return asNumber(row.offeredGames, row.gameCount);
}

function isPlayedMode() {
  return corpCardMode === 'played' && (combinationType === 'corp-card' || combinationType === 'card-card');
}

function isCardOnlyView() {
  return (combinationType === 'corp-card' || combinationType === 'prelude-card')
    && !$('#combinationSearch1').value.trim();
}

function isStandaloneView() {
  return COMBINATION_TYPES[combinationType].standalone === true
    || (combinationType === 'corp-prelude' && !$('#combinationSearch1').value.trim());
}

function standaloneKind() {
  return combinationType === 'corp-prelude' ? 'prelude' : 'corp';
}

function compareCombinationRows(left, right) {
  const metricSorts = new Set(['avgEloChange', 'winRate', 'lift1', 'lift2', 'totalLift']);
  const metricObservations = combinationSort === 'avgEloNotKept' ? 'notKeptGames' : 'gameCount';
  const valueForSort = row => combinationSort === 'gameCount' ? offeredGameCount(row)
    : metricSorts.has(combinationSort) || combinationSort === 'avgEloNotKept'
      ? metricForDisplay(eloValueForDisplay(row, combinationSort), row[metricObservations])
      : row[combinationSort];
  const a = valueForSort(left);
  const b = valueForSort(right);
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  const comparison = typeof a === 'number' && typeof b === 'number'
    ? a - b
    : String(a).localeCompare(String(b));
  return combinationDirection === 'asc' ? comparison : -comparison;
}

function corporationAdjustmentActive() {
  return combinationType === 'corp-card'
    && adjustCorporationElo
    && Boolean($('#combinationSearch1').value.trim());
}

function eloValueForDisplay(row, metric) {
  const value = nullableNumber(row[metric]);
  if (!corporationAdjustmentActive() || !['avgEloChange', 'avgEloNotKept'].includes(metric)) return value;
  const baseline = nullableNumber(row.corporationBaselineElo);
  return value === null || baseline === null ? null : value - baseline;
}

function aiContextText() {
  const config = COMBINATION_TYPES[combinationType];
  const standalone = isStandaloneView();
  const cardOnly = isCardOnlyView() || (isPlayedMode() && combinationType === 'card-card');
  const playedMode = isPlayedMode();
  const mode = playedMode ? `${cardOnly ? 'Card' : 'Corporation + card'} play decisions`
    : standalone ? `${standaloneKind() === 'corp' ? 'Corporation' : 'Prelude'} rankings`
    : cardOnly ? 'Card rankings' : config.label;
  const generationValue = playedMode
    ? playGenerationValue($('#combinationDraftNumber').value)
    : draftGenerationValue($('#combinationDraftNumber').value);
  const generation = generationValue || 'Starting hand';
  const minimum = requestedMetricMinimum();
  const searchContext = [1, 2, 3, 4, 5].flatMap(index => {
    const label = $(`#combinationSearch${index}Label`);
    if (!label || label.hidden) return [];
    const name = label.querySelector('span').textContent;
    const value = $(`#combinationSearch${index}`).value.trim() || '(none)';
    return [`${name}: ${value}`];
  });
  return [
    'Terraforming Mars Statistics — current context',
    `Mode: ${mode}`,
    `Cohort: 2-player ranked · Prelude ${settings.prelude ? 'on' : 'off'} · Draft on · Colonies off`,
    `Maps: ${settings.maps.join(', ')}`,
    `Average table Elo: ${selectedEloRange()[1].label}`,
    `${playedMode ? 'Play' : generationValue ? 'Draft' : 'Starting hand'} generation: ${generation}`,
    `Metric minimum: ${minimum} observations`,
    `Elo display: ${corporationAdjustmentActive() ? 'adjusted by corporation cohort average' : 'raw average gain'}`,
    ...searchContext,
    playedMode
      ? 'Available Games counts cards bought by this generation and not played earlier. Played Rate is the share played in this generation; Not Played includes cards played later or never recorded as played.'
      : config.kind1 === 'card' || config.kind2 === 'card'
      ? generationValue
        ? 'Drafted Games counts cards positively identified as a player\'s selections during the rotating research draft. The automatically received fourth card is usually unavailable in the public export. Bought Rate is the share included in cards_kept.'
        : 'Starting-hand values count the initial cards offered before research drafts. Kept Rate is the share included in the player\'s kept starting hand.'
      : 'This mode contains no project card, so draft generation does not apply.',
  ].join('\n');
}

function renderAiContext() {
  const field = $('#aiContext');
  if (field) field.value = aiContextText();
}

async function copyAiContext() {
  const text = aiContextText();
  const field = $('#aiContext');
  try {
    await navigator.clipboard.writeText(text);
    toast('AI context copied');
  } catch {
    field.focus();
    field.select();
    document.execCommand('copy');
    toast('AI context selected and copied');
  }
}

function renderCombinationControls() {
  const config = COMBINATION_TYPES[combinationType];
  const usesCards = config.kind1 === 'card' || config.kind2 === 'card';
  const standalone = isStandaloneView();
  const playedMode = isPlayedMode();
  const cardOnly = isCardOnlyView() || (playedMode && combinationType === 'card-card');
  const standaloneLabel = standaloneKind() === 'prelude' ? 'Prelude' : 'Corporation';
  const singleItem = cardOnly || standalone;
  const supportsNotKept = playedMode || standalone || combinationType === 'corp-prelude' || combinationType === 'corp-card' || combinationType === 'prelude-card';
  const hasCards = config.kind1 === 'card' || config.kind2 === 'card';
  const purchaseGeneration = playedMode ? playGenerationValue($('#combinationDraftNumber').value) : draftGenerationValue($('#combinationDraftNumber').value);
  const draftMode = !playedMode && Boolean(purchaseGeneration);
  const cardPurchaseLabels = !playedMode && (hasCards || cardOnly);
  const metricMinimum = requestedMetricMinimum();
  $$('[data-combination-type]').forEach(button => {
    const selected = button.dataset.combinationType === combinationType;
    button.classList.toggle('active', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
  const supportsPlayMode = combinationType === 'corp-card' || combinationType === 'card-card';
  $('#corpCardMetricTabs').hidden = !supportsPlayMode;
  $('#corpCardMetricTabs').querySelector('span').textContent = combinationType === 'card-card' ? 'Card play values' : 'Corp + Card values';
  $('#eloAdjustControl').hidden = combinationType !== 'corp-card';
  $('#adjustCorporationElo').checked = adjustCorporationElo;
  $('#adjustCorporationElo').disabled = !$('#combinationSearch1').value.trim();
  $$('[data-corp-card-mode]').forEach(button => {
    const selected = button.dataset.corpCardMode === corpCardMode;
    button.classList.toggle('active', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
  $('#combinationRankingTitle').textContent = playedMode
    ? `${cardOnly ? 'Card' : 'Corporation + Card'} Play Rankings`
    : standalone ? `${standaloneLabel} Rankings` : cardOnly ? 'Card Rankings' : `${config.label} Rankings`;
  const fourCardSearches = combinationType === 'corp-card';
  const fourCorporationSearches = combinationType === 'corporations';
  const corpPrelude = combinationType === 'corp-prelude';
  $('.filter-card').classList.toggle('four-card-searches', fourCardSearches);
  $('.filter-card').classList.toggle('two-prelude-searches', corpPrelude);
  $('#combinationSlot1FilterLabel').textContent = fourCorporationSearches ? 'Corporation 1' : corpPrelude ? 'Corporation (optional)' : standalone ? `Search ${standaloneLabel.toLocaleLowerCase()}s` : cardOnly ? `${config.slot1} (optional)` : config.slot1;
  const supportsSecondItemSearch = combinationType === 'corp-card' || combinationType === 'corp-prelude';
  $('#combinationSlot2FilterLabel').textContent = fourCorporationSearches ? 'Corporation 2' : corpPrelude ? 'Prelude' : supportsSecondItemSearch ? `${config.slot2} 1` : config.slot2;
  $('#combinationSlot1Heading').textContent = config.slot1;
  $('#combinationSlot2Heading').textContent = standalone ? standaloneLabel : config.slot2;
  $('#combinationGamesHeading').textContent = playedMode ? 'Available Games' : draftMode ? 'Drafted Games' : cardPurchaseLabels ? 'Offered Games' : 'Games';
  $('#combinationKeepRateHeading').textContent = playedMode ? 'Played Rate' : draftMode ? 'Bought Rate' : cardPurchaseLabels ? 'Kept Rate' : 'Selection Rate';
  const eloPrefix = corporationAdjustmentActive() ? 'Avg Elo Adjusted' : 'Avg Elo';
  $('#combinationKeptEloHeading').textContent = playedMode ? `${eloPrefix} · Played` : draftMode ? `${eloPrefix} · Bought` : cardPurchaseLabels ? `${eloPrefix} · Kept` : `${eloPrefix} · Selected`;
  $('#combinationNotKeptEloHeading').textContent = playedMode ? `${eloPrefix} · Not Played` : draftMode ? `${eloPrefix} · Not Bought` : cardPurchaseLabels ? `${eloPrefix} · Not Kept` : `${eloPrefix} · Not Selected`;
  $('#combinationKeptWinRateHeading').textContent = playedMode ? 'Win Rate · Played' : draftMode ? 'Win Rate · Bought' : cardPurchaseLabels ? 'Win Rate · Kept' : 'Win Rate · Selected';
  $('#combinationLift1Heading').textContent = config.slot1;
  $('#combinationLift2Heading').textContent = config.slot2;
  $('#combinationSearch1').placeholder = corpPrelude ? 'Leave empty for prelude rankings...' : standalone ? `Search ${standaloneLabel.toLocaleLowerCase()}...` : cardOnly ? 'Leave empty for card rankings...' : `Search ${config.slot1.toLocaleLowerCase()}...`;
  $('#combinationSearch2').placeholder = fourCardSearches ? 'Search card...' : fourCorporationSearches ? 'Search second corporation...' : `Search ${config.slot2.toLocaleLowerCase()}...`;
  $('#combinationSearch2Label').hidden = standalone && !fourCorporationSearches && !corpPrelude;
  $('#combinationSearch3Label').hidden = !(supportsSecondItemSearch || fourCorporationSearches);
  $('#combinationSlot3FilterLabel').textContent = fourCorporationSearches ? 'Corporation 3' : corpPrelude ? 'Prelude' : `${config.slot2} 2`;
  $('#combinationSearch3').placeholder = fourCardSearches ? 'Search card...' : fourCorporationSearches ? 'Search third corporation...' : `Search second ${config.slot2.toLocaleLowerCase()}...`;
  $('#combinationSearch4Label').hidden = !(fourCardSearches || fourCorporationSearches);
  $('#combinationSlot4FilterLabel').textContent = fourCorporationSearches ? 'Corporation 4' : 'Card 3';
  $('#combinationSearch4').placeholder = fourCardSearches ? 'Search card...' : fourCorporationSearches ? 'Search fourth corporation...' : 'Search third card...';
  $('#combinationSearch5Label').hidden = !fourCardSearches;
  $('#combinationSlot5FilterLabel').textContent = 'Card 4';
  $('#combinationSearch5').placeholder = 'Search card...';
  $('#combinationDraftNumber').disabled = !usesCards;
  $('#combinationGenerationControl').hidden = !usesCards;
  $('#combinationDraftNumber').min = playedMode ? '1' : '2';
  $('#combinationDraftNumber').max = '14';
  $('#combinationGenerationLabel').textContent = playedMode ? 'Play generation' : 'Draft generation (optional)';
  $('#combinationDraftNumber').placeholder = playedMode ? 'Leave empty for Gen 1' : usesCards ? 'Leave empty for starting hand' : 'Not used for this type';
  $('#combinationDraftNote').textContent = playedMode
    ? `Generation ${purchaseGeneration}: includes cards bought in or before this generation and not played earlier. “Played” means played now; “Not Played” means played later or never recorded as played. The export does not record when cards are sold or discarded.`
    : usesCards && draftMode
    ? `Generation ${purchaseGeneration} is research draft number ${Number(purchaseGeneration) - 1}; generation 2 is the first normal four-card research draft. Generation-1 setup and card-effect artifacts are excluded. “Drafted” means the card was actively selected by the player during the rotating draft, and “Bought” means it was included in cards_kept. The automatic fourth card is usually missing.`
    : usesCards
    ? 'Starting Hand: leave Draft generation empty to analyze the initial cards offered before research drafts.'
    : 'Draft generation does not apply because this combination contains no project card.';
  $('#combinationReliabilityNote').textContent = playedMode
    ? `Leave Corporation empty for card-only play rankings, or enter one to condition the results on it. Elo and win-rate values need ${metricMinimum} played or not-played observations, otherwise they are shown as —. Average Elo is the player's final whole-game rating change, not Elo caused immediately by playing the card.`
    : standalone
    ? `${standaloneLabel}s are ranked by offers and selections. Every row remains visible; Elo and win-rate values need ${metricMinimum} selected or not-selected observations, otherwise they are shown as —.`
    : cardOnly && draftMode
    ? `Cards are ranked from selections positively attributed to a player during the rotating draft; the automatic fourth card is usually missing. Enter a ${config.slot1.toLocaleLowerCase()} to condition the result on it. Every row remains visible; Elo and win-rate values need ${metricMinimum} bought or not-bought observations, otherwise they are shown as —.`
    : cardOnly
    ? `Cards are ranked from the initial starting hand. Enter a ${config.slot1.toLocaleLowerCase()} to condition the result on it. Every row remains visible; Elo and win-rate values need ${metricMinimum} kept or not-kept observations, otherwise they are shown as —.`
    : supportsNotKept
      ? draftMode
        ? `Every card row was selected by the player during the rotating draft; “Bought” means the player then paid for it. The automatic fourth card is usually missing. Elo and win-rate values need ${metricMinimum} bought or not-bought observations, otherwise they are shown as —.`
        : `Every card row was in the player's initial starting hand; “Kept” means the player paid for it. Elo and win-rate values need ${metricMinimum} kept or not-kept observations, otherwise they are shown as —.`
      : `Every row remains visible; Elo, win-rate, and lift values need ${metricMinimum} games, otherwise they are shown as —.`;
  $$('[data-pair-only-column]').forEach(column => { column.hidden = singleItem; });
  $$('[data-lift-column]').forEach(column => { column.hidden = singleItem || playedMode; });
  $$('[data-card-metric-column]').forEach(column => { column.hidden = !supportsNotKept; });
  $$('[data-keep-rate-column]').forEach(column => { column.hidden = false; });
  $$('[data-combo-sort]').forEach(button => {
    const indicator = button.lastElementChild;
    if (indicator) indicator.textContent = button.dataset.comboSort === combinationSort
      ? (combinationDirection === 'asc' ? '↑' : '↓') : '↕';
  });
  renderAiContext();
}

function renderCombinationItem(name, kind) {
  const image = cardImage(name, kind);
  return `<div class="combination-item" tabindex="0" data-card-preview="true" data-card-name="${safe(name)}" data-card-kind="${safe(kind)}" data-card-image="${safe(image)}"><img src="${safe(image)}" alt="" onerror="this.hidden=true" /><span>${safe(name)}</span></div>`;
}

function renderCombinations() {
  hideCardPreview();
  const config = COMBINATION_TYPES[combinationType];
  const cardOnly = isCardOnlyView() || (isPlayedMode() && combinationType === 'card-card');
  const standalone = isStandaloneView();
  const playedMode = isPlayedMode();
  const singleItem = cardOnly || standalone;
  const supportsNotKept = playedMode || standalone || combinationType === 'corp-prelude' || combinationType === 'corp-card' || combinationType === 'prelude-card';
  const showsNotKept = supportsNotKept;
  const search1 = $('#combinationSearch1').value;
  const search2 = $('#combinationSearch2').value;
  const search3 = $('#combinationSearch3').value;
  const search4 = $('#combinationSearch4').value;
  const search5 = $('#combinationSearch5').value;
  let rows;
  if (playedMode) {
    const corporationRows = combinationType === 'corp-card' && search1.trim()
      ? filterRowsBySearch(playedRows, row => row.corporation, search1) : playedRows;
    const candidates = cardOnly ? aggregatePlayedByCard(corporationRows) : corporationRows;
    const cardSearches = (combinationType === 'corp-card' ? [search2, search3, search4, search5] : [search1, search2])
      .map(value => value.trim()).filter(Boolean);
    const sortedCandidates = candidates.map(playedRowAsCombination).sort(compareCombinationRows);
    rows = filterRowsByOrderedSearch(sortedCandidates, row => row.name2, cardSearches);
  } else {
    if (combinationType === 'corporations') {
      rows = filterRowsByOrderedSearch(combinations.sort(compareCombinationRows), row => row.name2, [search1, search2, search3, search4]);
    } else {
      const firstMatches = filterRowsBySearch(combinations, row => standalone ? row.name2 : row.name1, search1);
      const itemSearches = (combinationType === 'corp-card' ? [search2, search3, search4, search5] : [search2, search3])
        .map(value => value.trim()).filter(Boolean);
      rows = filterRowsByOrderedSearch(firstMatches.sort(compareCombinationRows), row => row.name2, itemSearches);
    }
  }
  const pageSize = asNumber($('#combinationRowsPerPage').value, 50);
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  combinationPage = Math.min(combinationPage, pages);
  const start = (combinationPage - 1) * pageSize;
  const visible = rows.slice(start, start + pageSize);
  const noun = standalone ? 'corporations' : cardOnly ? 'cards' : 'combinations';
  $('#combinationShowing').textContent = rows.length ? `Showing ${start + 1}-${start + visible.length} of ${fmt(rows.length)} ${noun}` : `Showing 0 ${noun}`;
  $('#combinationPageNumber').textContent = `Page ${combinationPage} of ${pages}`;
  $('#previousCombinationPage').disabled = combinationPage <= 1;
  $('#nextCombinationPage').disabled = combinationPage >= pages;
  $('#combinationTable').innerHTML = visible.length ? visible.map(row => {
    const keptMetric = metricForDisplay(eloValueForDisplay(row, 'avgEloChange'), row.gameCount);
    const notKeptMetric = metricForDisplay(eloValueForDisplay(row, 'avgEloNotKept'), row.notKeptGames);
    const winRateMetric = metricForDisplay(row.winRate, row.gameCount);
    const lift1Metric = metricForDisplay(row.lift1, row.gameCount);
    const lift2Metric = metricForDisplay(row.lift2, row.gameCount);
    const totalLiftMetric = metricForDisplay(row.totalLift, row.gameCount);
    return `
    <tr data-corporation="${safe(row.name1 || '')}">
      ${singleItem ? '' : `<td>${renderCombinationItem(row.name1, config.kind1)}</td>`}
      <td>${renderCombinationItem(row.name2, standalone ? standaloneKind() : config.kind2)}</td>
      <td class="muted">${fmt(offeredGameCount(row))}</td>
      <td>${combinationPercent(row.keepRate)}</td>
      <td class="${tone(keptMetric)}">${combinationMetric(keptMetric)}</td>
      ${showsNotKept ? `<td class="${tone(notKeptMetric)}">${combinationMetric(notKeptMetric)}</td>` : ''}
      <td>${combinationPercent(winRateMetric)}</td>
      ${singleItem || playedMode ? '' : `<td class="${tone(lift1Metric)}">${combinationMetric(lift1Metric)}</td><td class="${tone(lift2Metric)}">${combinationMetric(lift2Metric)}</td><td class="${tone(totalLiftMetric)}">${combinationMetric(totalLiftMetric)}</td>`}
    </tr>`;
  }).join('') : `<tr><td colspan="${playedMode ? singleItem ? 6 : 7 : singleItem ? showsNotKept ? 6 : 5 : showsNotKept ? 10 : 9}" class="empty-cell">No local ${noun} match these filters.</td></tr>`;
  renderCombinationControls();
  saveViewState();
}

function normalizeDraftDetail(payload) {
  const rows = (Array.isArray(payload?.data) ? payload.data : []).map(row => ({
    generation: row.stage === 'starting_hand' ? 0 : asNumber(row.draftNumber),
    available: asNumber(row.offered), positive: asNumber(row.kept), negative: asNumber(row.notKept),
    rate: nullableNumber(row.keepRate) === null ? null : asNumber(row.keepRate) / 100,
    positiveElo: nullableNumber(row.eloKept), negativeElo: nullableNumber(row.eloNotKept),
    positiveWinRate: nullableNumber(row.winRateKept),
    corporationBaselineElo: nullableNumber(row.corporationBaselineElo),
  })).filter(row => row.available > 0);
  return smoothDraftDetail(rows);
}

function smoothDraftDetail(rows) {
  const byGeneration = new Map(rows.map(row => [row.generation, row]));
  const metrics = ['rate', 'positiveElo', 'negativeElo', 'positiveWinRate'];
  return rows.map(row => {
    const neighbors = row.generation === 0
      ? [byGeneration.get(2)]
      : [byGeneration.get(row.generation - 1), byGeneration.get(row.generation + 1)];
    const sources = [{row, weight: 0.6}, ...neighbors.filter(Boolean).map(neighbor => ({row: neighbor, weight: 0.2}))];
    const smoothed = {...row};
    metrics.forEach(metric => {
      const usable = sources.filter(source => nullableNumber(source.row[metric]) !== null);
      if (!usable.length) return;
      const weight = usable.reduce((total, source) => total + source.weight, 0);
      smoothed[metric] = usable.reduce((total, source) => total + source.weight * source.row[metric], 0) / weight;
    });
    return smoothed;
  });
}

function normalizePlayedDetail(payload) {
  return (Array.isArray(payload?.data) ? payload.data : []).map(row => ({
    generation: asNumber(row.generation), available: asNumber(row.available),
    positive: asNumber(row.played), negative: asNumber(row.notPlayed),
    rate: nullableNumber(row.playRate), positiveElo: nullableNumber(row.eloPlayed),
    negativeElo: nullableNumber(row.eloNotPlayed), positiveWinRate: nullableNumber(row.winRatePlayed),
    corporationBaselineElo: nullableNumber(row.corporationBaselineElo),
  })).filter(row => row.available > 0);
}

function renderCardDetail(rows, mode) {
  const played = mode === 'played';
  const adjusted = corporationAdjustmentActive() && Boolean(selectedDetailCorporation);
  const minimum = requestedMetricMinimum();
  $('#cardDetailMode').textContent = played ? 'PLAY DECISIONS BY GENERATION' : 'DRAFT BUYING BY GENERATION';
  $('#cardDetailName').textContent = selectedDetailCard;
  $('#cardDetailAvailableHeading').textContent = played ? 'Available' : 'Drafted';
  $('#cardDetailPositiveCountHeading').textContent = played ? 'Played' : 'Bought';
  $('#cardDetailNegativeCountHeading').textContent = played ? 'Not Played' : 'Not Bought';
  $('#cardDetailRateHeading').textContent = played ? 'Played Rate' : 'Bought Rate';
  const eloPrefix = adjusted ? 'Avg Elo Adjusted' : 'Avg Elo';
  $('#cardDetailPositiveEloHeading').textContent = played ? `${eloPrefix} · Played` : `${eloPrefix} · Bought`;
  $('#cardDetailNegativeEloHeading').textContent = played ? `${eloPrefix} · Not Played` : `${eloPrefix} · Not Bought`;
  $('#cardDetailWinHeading').textContent = played ? 'Win Rate · Played' : 'Win Rate · Bought';
  $('#cardDetailNote').textContent = played
    ? `Each row asks whether an available copy was played in that generation or remained unplayed. Elo and win rate require ${minimum} observations in the relevant group.`
    : `Starting Hand is the initial purchase decision; Gen 2 onward use cards selected during research drafts. The automatic fourth card is usually missing. Elo and win rate require ${minimum} bought or not-bought observations.`;
  if (adjusted) $('#cardDetailNote').textContent += ` Adjusted Elo subtracts ${selectedDetailCorporation}'s average Elo gain in this cohort.`;
  $('#cardDetailTable').innerHTML = rows.length ? rows.map(row => {
    const baseline = adjusted ? nullableNumber(row.corporationBaselineElo) : 0;
    const positiveValue = row.positiveElo === null || baseline === null ? null : row.positiveElo - baseline;
    const negativeValue = row.negativeElo === null || baseline === null ? null : row.negativeElo - baseline;
    const positiveElo = metricForDisplay(positiveValue, row.positive);
    const negativeElo = metricForDisplay(negativeValue, row.negative);
    const positiveWin = metricForDisplay(row.positiveWinRate, row.positive);
    return `<tr>
      <td><strong>${row.generation === 0 ? 'Starting Hand' : `Gen ${row.generation}`}</strong></td>
      <td>${fmt(row.available)}</td><td>${fmt(row.positive)}</td><td>${fmt(row.negative)}</td>
      <td>${combinationPercent(row.rate)}</td>
      <td class="${tone(positiveElo)}">${combinationMetric(positiveElo)}</td>
      <td class="${tone(negativeElo)}">${combinationMetric(negativeElo)}</td>
      <td>${combinationPercent(positiveWin)}</td>
    </tr>`;
  }).join('') : '<tr><td colspan="8" class="empty-cell">No generation data for this card and cohort.</td></tr>';
}

async function loadCardDetail(cardName = selectedDetailCard, scrollToPanel = false, corporationName = selectedDetailCorporation) {
  if (!cardName) return;
  selectedDetailCard = cardName;
  selectedDetailCorporation = corporationName || '';
  const panel = $('#cardDetail');
  panel.hidden = false;
  $('#cardDetailName').textContent = cardName;
  $('#cardDetailTable').innerHTML = '<tr><td colspan="8" class="empty-cell">Loading every generation…</td></tr>';
  saveViewState();
  if (scrollToPanel) panel.scrollIntoView({behavior: 'smooth', block: 'start'});
  const requestId = ++cardDetailRequestId;
  const mode = isPlayedMode() ? 'played' : 'draft';
  const query = cohortQuery();
  query.set('card', cardName);
  query.set('mode', mode);
  if (selectedDetailCorporation) query.set('corporation', selectedDetailCorporation);
  try {
    const payload = await fetchJson(`/api/card-breakdown?${query}`);
    if (requestId !== cardDetailRequestId || cardName !== selectedDetailCard) return;
    renderCardDetail(mode === 'played' ? normalizePlayedDetail(payload) : normalizeDraftDetail(payload), mode);
  } catch (error) {
    if (requestId !== cardDetailRequestId) return;
    $('#cardDetailTable').innerHTML = `<tr><td colspan="8" class="empty-cell">Card detail failed: ${safe(error.message)}</td></tr>`;
  }
}

async function loadCombinations(preservePage = false) {
  combinationsLoaded = true;
  const requestId = ++combinationRequestId;
  const playedMode = isPlayedMode();
  setStatus($('#combinationStatus'), $('#combinationMessage'), 'loading', playedMode ? 'Querying played-card statistics…' : 'Querying the local Parquet database…');
  try {
    const standalone = isStandaloneView();
    const cardOnlyRequest = isCardOnlyView();
    const playedQuery = cohortQuery();
    playedQuery.set('generation', String(playGenerationValue($('#combinationDraftNumber').value)));
    const payload = await fetchJson(playedMode
      ? `/api/played?${playedQuery}`
      : standalone ? `/api/items?${standaloneQuery(standaloneKind())}`
      : cardOnlyRequest ? `/api/starting-hands?${cardOnlyQuery()}` : `/api/combinations?${combinationQuery()}`);
    if (requestId !== combinationRequestId) return;
    directRankingMode = playedMode || standalone || cardOnlyRequest;
    if (playedMode) {
      playedRows = normalizePlayedPayload(payload);
      combinations = [];
    } else {
      playedRows = [];
      combinations = standalone ? normalizeStandalonePayload(payload)
        : cardOnlyRequest ? normalizeCardOnlyPayload(payload) : normalizeCombinationPayload(payload);
    }
    if (!preservePage) combinationPage = 1;
    renderCombinations();
    setStatus($('#combinationStatus'), $('#combinationMessage'), payload.source.games ? 'ready' : 'error', sourceDescription(payload.source));
    if (selectedDetailCard) loadCardDetail();
  } catch (error) {
    if (requestId !== combinationRequestId) return;
    combinations = [];
    playedRows = [];
    renderCombinations();
    setStatus($('#combinationStatus'), $('#combinationMessage'), 'error', `Local database query failed: ${error.message}`);
  }
}

function renderGen1Production(analysis) {
  $('#gen1ProductionCohort').textContent = `2 players · ${settings.prelude ? 'Prelude on' : 'Prelude off'} · ${selectedEloRange()[1].label} · ${settings.maps.join(', ')}`;
  $('#gen1EloPerMc').textContent = analysis.eloPerMc.toFixed(3);
  $('#gen1ModelError').textContent = analysis.weightedRmse.toFixed(3);
  $('#gen1AnchorCount').textContent = fmt(analysis.cards.length);
  const valueCard = value => `<div><strong>${value.valueMc.toFixed(2)} MC</strong><span>${safe(value.name === 'mc' ? 'MC production' : value.name[0].toUpperCase() + value.name.slice(1) + (value.kind === 'tag' ? ' tag' : ' production'))}</span></div>`;
  $('#gen1ProductionValues').innerHTML = analysis.values.filter(value => value.kind === 'production').map(valueCard).join('');
  $('#gen1TagValues').innerHTML = analysis.values.filter(value => value.kind === 'tag').map(valueCard).join('');
  $('#gen1ProductionTable').innerHTML = analysis.cards.map(card => `
    <tr>
      <td>${renderCombinationItem(card.name, 'card')}</td>
      <td>${Object.entries(card.production).map(([name, amount]) => `${amount > 0 ? '+' : ''}${amount} ${safe(name)}`).join(' · ') || 'None'}</td>
      <td>${card.totalCost.toFixed(0)} MC</td>
      <td>${fmt(card.playedGames)}</td>
      <td class="${tone(card.observedEloDelta)}">${signed(card.observedEloDelta, 3)}</td>
      <td class="${tone(card.predictedEloDelta)}">${signed(card.predictedEloDelta, 3)}</td>
      <td>${card.modeledFairValueMc.toFixed(1)} MC</td>
      <td class="${tone(card.modeledEfficiencyMc)}">${signed(card.modeledEfficiencyMc, 1)} MC</td>
    </tr>`).join('');
  const assumptions = analysis.assumptions;
  $('#gen1ProductionAssumptions').textContent = `Assumptions: card purchase ${assumptions.cardPurchaseCost} MC · VP ${assumptions.victoryPointValueMc} MC. Production and ${assumptions.estimatedTags.join(', ')} tag values are estimated together with non-negative weighted least squares. A zero means the data did not identify an additional positive linear value after accounting for the card's other features—not that the tag is literally worthless. Tag option value can be nonlinear, especially for Jovians. Observed Elo delta is calculated within each corporation, then weighted by Gen-1 plays; these are strategic associations, not guaranteed causal prices.`;
}

async function loadGen1Production() {
  setStatus($('#gen1ProductionStatus'), $('#gen1ProductionMessage'), 'loading', 'Fitting the Gen-1 MC-production model…');
  try {
    const payload = await fetchJson(`/api/gen1-production?${cohortQuery()}`);
    renderGen1Production(payload.analysis);
    setStatus($('#gen1ProductionStatus'), $('#gen1ProductionMessage'), 'ready', sourceDescription(payload.source));
  } catch (error) {
    $('#gen1ProductionTable').innerHTML = `<tr><td colspan="8" class="empty-cell">Production model failed: ${safe(error.message)}</td></tr>`;
    setStatus($('#gen1ProductionStatus'), $('#gen1ProductionMessage'), 'error', `Production model failed: ${error.message}`);
  }
}

function normalizePlayedPayload(payload) {
  const rows = Array.isArray(payload?.played) ? payload.played : [];
  return rows.map(row => ({
    corporation: String(row.corporation ?? ''), card: String(row.card ?? ''),
    acquiredGames: asNumber(row.acquiredGames), playedGames: asNumber(row.playedGames), notPlayedGames: asNumber(row.notPlayedGames),
    playRate: nullableNumber(row.playRate), avgEloPlayed: nullableNumber(row.avgEloPlayed),
    avgEloNotPlayed: nullableNumber(row.avgEloNotPlayed), winRatePlayed: nullableNumber(row.winRatePlayed),
    corporationBaselineElo: nullableNumber(row.corporationBaselineElo),
  })).filter(row => row.corporation && row.card && row.acquiredGames > 0);
}

function aggregatePlayedByCard(rows) {
  const cards = new Map();
  for (const row of rows) {
    let card = cards.get(row.card);
    if (!card) {
      card = {
        corporation: '', card: row.card,
        acquiredGames: 0, playedGames: 0, notPlayedGames: 0,
        playedEloTotal: 0, playedEloGames: 0,
        notPlayedEloTotal: 0, notPlayedEloGames: 0,
        playedWinTotal: 0, playedWinGames: 0,
        baselineEloTotal: 0, baselineEloGames: 0,
      };
      cards.set(row.card, card);
    }
    card.acquiredGames += row.acquiredGames;
    card.playedGames += row.playedGames;
    card.notPlayedGames += row.notPlayedGames;
    if (row.avgEloPlayed !== null && row.playedGames > 0) {
      card.playedEloTotal += row.avgEloPlayed * row.playedGames;
      card.playedEloGames += row.playedGames;
    }
    if (row.avgEloNotPlayed !== null && row.notPlayedGames > 0) {
      card.notPlayedEloTotal += row.avgEloNotPlayed * row.notPlayedGames;
      card.notPlayedEloGames += row.notPlayedGames;
    }
    if (row.winRatePlayed !== null && row.playedGames > 0) {
      card.playedWinTotal += row.winRatePlayed * row.playedGames;
      card.playedWinGames += row.playedGames;
    }
    if (row.corporationBaselineElo !== null && row.acquiredGames > 0) {
      card.baselineEloTotal += row.corporationBaselineElo * row.acquiredGames;
      card.baselineEloGames += row.acquiredGames;
    }
  }
  return [...cards.values()].map(card => ({
    corporation: '', card: card.card,
    acquiredGames: card.acquiredGames,
    playedGames: card.playedGames,
    notPlayedGames: card.notPlayedGames,
    playRate: card.acquiredGames ? card.playedGames / card.acquiredGames : null,
    avgEloPlayed: card.playedEloGames ? card.playedEloTotal / card.playedEloGames : null,
    avgEloNotPlayed: card.notPlayedEloGames ? card.notPlayedEloTotal / card.notPlayedEloGames : null,
    winRatePlayed: card.playedWinGames ? card.playedWinTotal / card.playedWinGames : null,
    corporationBaselineElo: card.baselineEloGames ? card.baselineEloTotal / card.baselineEloGames : null,
  }));
}

function playedRowAsCombination(row) {
  return {
    name1: row.corporation,
    name2: row.card,
    gameCount: row.playedGames,
    offeredGames: row.acquiredGames,
    notKeptGames: row.notPlayedGames,
    keepRate: row.playRate,
    avgEloChange: row.avgEloPlayed,
    avgEloNotKept: row.avgEloNotPlayed,
    corporationBaselineElo: row.corporationBaselineElo,
    winRate: row.winRatePlayed,
    lift1: null,
    lift2: null,
    totalLift: null,
  };
}

function showPage(name, updateHash = true) {
  if (name === 'combinations' || name === 'played') name = 'drafting';
  if (!document.querySelector(`[data-page="${name}"]`)) name = 'drafting';
  $$('.page').forEach(page => page.classList.toggle('active', page.dataset.page === name));
  $$('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.pageLink === name));
  if (updateHash) history.replaceState(null, '', `#${name}`);
  $('#sidebar').classList.remove('mobile-open');
  $('#sidebarScrim').classList.remove('show');
  hideCardPreview();
  if (name !== 'drafting') clearCardDetail();
  saveViewState();
  window.scrollTo({top:0, behavior:'instant'});
  if (name === 'drafting' && !combinationsLoaded) loadCombinations(true);
  if (name === 'gen1-production') loadGen1Production();
}

function clearCardDetail() {
  selectedDetailCard = '';
  selectedDetailCorporation = '';
  cardDetailRequestId += 1;
  $('#cardDetail').hidden = true;
}

function modifierClick(event) {
  return event.ctrlKey || event.metaKey || event.button === 1;
}

function newTabUrl(page, combination = '') {
  const url = new URL(location.href);
  if (combination) url.searchParams.set('combination', combination);
  else url.searchParams.delete('combination');
  url.hash = page;
  return url.href;
}

function toast(message) {
  const element = $('#toast');
  element.textContent = message;
  element.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.remove('show'), 3200);
}

$$('[data-page-link]').forEach(button => button.addEventListener('click', event => {
  if (modifierClick(event)) {
    window.open(newTabUrl(button.dataset.pageLink), '_blank', 'noopener');
    return;
  }
  showPage(button.dataset.pageLink);
}));
$('#collapseButton').addEventListener('click', () => $('#sidebar').classList.toggle('collapsed'));
$('#menuButton').addEventListener('click', () => { $('#sidebar').classList.add('mobile-open'); $('#sidebarScrim').classList.add('show'); });
$('#sidebarScrim').addEventListener('click', () => { $('#sidebar').classList.remove('mobile-open'); $('#sidebarScrim').classList.remove('show'); });
$('#copyAiContext').addEventListener('click', copyAiContext);
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
$('#combinationSearch1').addEventListener('input', () => {
  combinationPage = 1;
  if (selectedDetailCard) clearCardDetail();
  if (isPlayedMode()) {
    renderCombinations();
    saveViewState();
    return;
  }
  const shouldUseDirectRankings = isStandaloneView() || isCardOnlyView();
  if (shouldUseDirectRankings !== directRankingMode) {
    directRankingMode = shouldUseDirectRankings;
    loadCombinations();
  }
  else renderCombinations();
  saveViewState();
});
$('#combinationSearch2').addEventListener('input', () => { combinationPage = 1; renderCombinations(); saveViewState(); });
$('#combinationSearch3').addEventListener('input', () => { combinationPage = 1; renderCombinations(); saveViewState(); });
$('#combinationSearch4').addEventListener('input', () => { combinationPage = 1; renderCombinations(); saveViewState(); });
$('#combinationSearch5').addEventListener('input', () => { combinationPage = 1; renderCombinations(); saveViewState(); });
$('#combinationDraftNumber').addEventListener('input', event => {
  combinationPage = 1;
  const input = event.currentTarget;
  // Keep a temporary "1" while the user is entering Gen 10–14. Clearing it
  // on every keystroke made those valid two-digit draft generations impossible.
  const number = Number(input.value);
  if (input.value.trim() && (!Number.isInteger(number) || number < 1 || number > 14)) input.value = '';
  saveViewState();
  loadCombinations();
});
$('#combinationDraftNumber').addEventListener('change', event => {
  const input = event.currentTarget;
  if (!isPlayedMode() && input.value.trim() && !draftGenerationValue(input.value)) input.value = '';
  saveViewState();
  renderCombinationControls();
});
$('#combinationMinimumGames').addEventListener('input', () => { combinationPage = 1; renderCombinations(); saveViewState(); });
$('#adjustCorporationElo').addEventListener('change', event => {
  adjustCorporationElo = event.currentTarget.checked;
  combinationPage = 1;
  renderCombinations();
  if (selectedDetailCard) loadCardDetail();
  saveViewState();
});
function selectCombinationType(type) {
  const oldConfig = COMBINATION_TYPES[combinationType];
  combinationSearchMemory[oldConfig.kind1] = $('#combinationSearch1').value;
  combinationSearchMemory[oldConfig.kind2] = $('#combinationSearch2').value;
  combinationType = type;
  clearCardDetail();
  if (!['corp-card', 'card-card'].includes(type)) corpCardMode = 'draft';
  $('#combinationDraftNumber').value = draftGenerationValue($('#combinationDraftNumber').value);
  const nextConfig = COMBINATION_TYPES[combinationType];
  combinationPage = 1;
  combinationSort = isStandaloneView() || isCardOnlyView() ? 'avgEloChange' : 'totalLift';
  combinationDirection = 'desc';
  $('#combinationSearch1').value = combinationSearchMemory[nextConfig.kind1] || '';
  $('#combinationSearch2').value = combinationSearchMemory[nextConfig.kind2] || '';
  $('#combinationSearch3').value = '';
  $('#combinationSearch4').value = '';
  $('#combinationSearch5').value = '';
  renderCombinationControls();
  saveViewState();
  loadCombinations();
}

$$('[data-corp-card-mode]').forEach(button => button.addEventListener('click', () => {
  if (!['corp-card', 'card-card'].includes(combinationType) || button.dataset.corpCardMode === corpCardMode) return;
  corpCardMode = button.dataset.corpCardMode;
  $('#combinationDraftNumber').value = '';
  combinationPage = 1;
  combinationSort = 'avgEloChange';
  combinationDirection = 'desc';
  renderCombinationControls();
  loadCombinations();
}));

$$('[data-combination-type]').forEach(button => button.addEventListener('click', event => {
  if (modifierClick(event)) {
    window.open(newTabUrl('drafting', button.dataset.combinationType), '_blank', 'noopener');
    return;
  }
  selectCombinationType(button.dataset.combinationType);
}));
$('#refreshGen1Production').addEventListener('click', loadGen1Production);
$('#combinationRowsPerPage').addEventListener('change', () => { combinationPage = 1; renderCombinations(); saveViewState(); });
$('#previousCombinationPage').addEventListener('click', () => { combinationPage = Math.max(1, combinationPage - 1); renderCombinations(); saveViewState(); });
$('#nextCombinationPage').addEventListener('click', () => { combinationPage += 1; renderCombinations(); saveViewState(); });
$('.combination-table thead').addEventListener('click', event => {
  const button = event.target.closest('[data-combo-sort]');
  if (!button) return;
  const key = button.dataset.comboSort;
  if (combinationSort === key) combinationDirection = combinationDirection === 'asc' ? 'desc' : 'asc';
  else { combinationSort = key; combinationDirection = key.startsWith('name') ? 'asc' : 'desc'; }
  combinationPage = 1;
  renderCombinations();
  saveViewState();
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

['combinationTable', 'gen1ProductionTable'].forEach(id => {
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
    if (target && target.matches(':focus-visible')) showCardPreview(target);
  });
  table.addEventListener('focusout', hideCardPreview);
  table.addEventListener('mouseleave', hideCardPreview);
});
$('#combinationTable').addEventListener('click', event => {
  const target = event.target.closest('[data-card-preview]');
  if (!target || target.dataset.cardKind !== 'card') return;
  loadCardDetail(target.dataset.cardName, true, target.closest('tr')?.dataset.corporation || '');
});
$('#closeCardDetail').addEventListener('click', () => {
  clearCardDetail();
  saveViewState();
});
$('#cardPreviewImage').addEventListener('error', hideCardPreview);
document.addEventListener('pointerdown', hideCardPreview, true);
document.addEventListener('keydown', event => { if (event.key === 'Escape') hideCardPreview(); });
window.addEventListener('scroll', hideCardPreview, true);
window.addEventListener('resize', hideCardPreview);
window.addEventListener('blur', hideCardPreview);
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

window.__marsStatsTest = {normalizeStartingPayload, normalizeCombinationPayload, normalizeCardOnlyPayload, normalizeStandalonePayload, normalizePlayedPayload, aggregatePlayedByCard, playedRowAsCombination, normalizeDraftDetail, normalizePlayedDetail, smoothDraftDetail, normalizeViewState, draftGenerationValue, playGenerationValue, playGenerationInputValue, fuzzySearchMatches, filterRowsBySearch, filterRowsByOrderedSearch, metricWithMinimum, signed};
restoreViewState();
renderSettings();
renderCombinationControls();
showPage(location.hash.slice(1) || 'drafting', false);
