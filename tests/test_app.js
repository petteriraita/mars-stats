'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync(new URL('../app.js', `file://${__filename}`), 'utf8');
const html = fs.readFileSync(new URL('../index.html', `file://${__filename}`), 'utf8');
assert.strictEqual((html.match(/data-lift-column/g) || []).length, 3);
assert.ok(html.includes('id="combinationSearch5"'));
assert.ok(source.includes("column.hidden = singleItem || playedMode"));
const definitions = source.split("$$('[data-page-link]')")[0];
const context = {Intl, URLSearchParams, console};
vm.createContext(context);
vm.runInContext(`${definitions}\nthis.api = {normalizeStartingPayload, normalizeCombinationPayload, normalizeCardOnlyPayload, normalizeStandalonePayload, normalizePlayedPayload, aggregatePlayedByCard, playedRowAsCombination, normalizeDraftDetail, normalizePlayedDetail, normalizeViewState, draftGenerationValue, playGenerationValue, playGenerationInputValue, fuzzySearchMatches, filterRowsBySearch, filterRowsByOrderedSearch, metricWithMinimum, signed};`, context);

const starting = context.api.normalizeStartingPayload({data: [{
  cardName: 'Cartel', offeredGames: 200, keptGames: 100, notKeptGames: 100,
  keepRate: 50, winRateKept: 60, avgEloGainOffered: 1, avgEloGainKept: 4,
  avgEloGainNotKept: -2, avgEloDeltaOffered: 0.75,
  avgEloDeltaKept: 3.75, avgEloDeltaNotKept: -2.25,
}]});
assert.strictEqual(starting.length, 1);
assert.strictEqual(starting[0].name, 'Cartel');
assert.strictEqual(starting[0].eloOffered, 1);
assert.strictEqual(starting[0].eloKept, 4);
assert.strictEqual(starting[0].eloNotKept, -2);
assert.strictEqual(starting[0].winRate, 60);
assert.strictEqual(context.api.signed(null), '—');
assert.strictEqual(context.api.signed(-2), '−2.00');
assert.strictEqual(context.api.fuzzySearchMatches('Industrial Center', 'indus center'), true);
assert.strictEqual(context.api.fuzzySearchMatches('Industrial Center', 'idl cntr'), true);
assert.strictEqual(context.api.fuzzySearchMatches('Industrial Center', 'indus asteroid'), false);
assert.strictEqual(context.api.fuzzySearchMatches('Food Factory', 'food fa'), true);
assert.strictEqual(context.api.fuzzySearchMatches('Beam From a Thorium Asteroid', 'food fa'), false);
assert.strictEqual(context.api.fuzzySearchMatches('Beam From a Thorium Asteroid', 'beam'), true);
assert.strictEqual(context.api.fuzzySearchMatches('Lunar Beam', 'beam'), true);
const searchRows = [{name: 'Ants'}, {name: 'Advanced Alloys'}, {name: 'Artificial Lake'}];
assert.strictEqual(context.api.filterRowsBySearch(searchRows, row => row.name, 'ants').map(row => row.name).join(','), 'Ants');
assert.strictEqual(context.api.filterRowsBySearch(searchRows, row => row.name, 'ANTS').map(row => row.name).join(','), 'Ants');
assert.strictEqual(context.api.filterRowsBySearch(searchRows, row => row.name, 'adv').map(row => row.name).join(','), 'Advanced Alloys');
const orderedSearchRows = [
  {name: 'Food Factory'}, {name: 'Beam From a Thorium Asteroid'}, {name: 'Windmills'},
];
assert.strictEqual(
  context.api.filterRowsByOrderedSearch(orderedSearchRows, row => row.name, ['windmills', 'food fa']).map(row => row.name).join(','),
  'Windmills,Food Factory',
);
assert.strictEqual(
  context.api.filterRowsByOrderedSearch(
    [{name: 'Arctic Algae'}, {name: 'Biomass Combustors'}], row => row.name, ['biomass', 'arctic'],
  ).map(row => row.name).join(','),
  'Biomass Combustors,Arctic Algae',
);
assert.strictEqual(
  context.api.filterRowsByOrderedSearch(
    [{name: 'Ecoline'}, {name: 'CrediCor'}, {name: 'Saturn Systems'}, {name: 'Inventrix'}],
    row => row.name, ['saturn', 'ecoline', 'inventrix', 'credi'],
  ).map(row => row.name).join(','),
  'Saturn Systems,Ecoline,Inventrix,CrediCor',
);

const sparse = context.api.normalizeStartingPayload({data: [{
  cardName: 'Sparse card', offeredGames: 105, keptGames: 5, notKeptGames: 100,
  keepRate: 4.8, avgEloGainOffered: 2, avgEloGainKept: 20, avgEloGainNotKept: 1,
}]})[0];
assert.strictEqual(sparse.eloOffered, 2);
assert.strictEqual(sparse.eloKept, 20);
assert.strictEqual(sparse.eloNotKept, 1);
assert.strictEqual(context.api.metricWithMinimum(99, 99), null);
assert.strictEqual(context.api.metricWithMinimum(99, 100), 99);

const combinations = context.api.normalizeCombinationPayload({combinations: [{
  name1: 'Cartel', name2: 'Earth Office', gameCount: 100, offeredGames: 150, keepRate: 2 / 3, winRate: 0.55,
  avgEloChange: 4, avgEloNotKept: -2, notKeptGames: 125, baseline1Elo: 0.5, baseline2Elo: 0.25,
  corporationBaselineElo: 0.75,
  lift1: 3.5, lift2: 3.75, totalLift: 3.25,
}]});
assert.strictEqual(combinations.length, 1);
assert.strictEqual(combinations[0].name1, 'Cartel');
assert.strictEqual(combinations[0].avgEloChange, 4);
assert.strictEqual(combinations[0].avgEloNotKept, -2);
assert.strictEqual(combinations[0].notKeptGames, 125);
assert.strictEqual(combinations[0].offeredGames, 150);
assert.strictEqual(combinations[0].keepRate, 2 / 3);
assert.strictEqual(combinations[0].totalLift, 3.25);
assert.strictEqual(combinations[0].corporationBaselineElo, 0.75);

const cardOnly = context.api.normalizeCardOnlyPayload({data: [{
  cardName: 'Cartel', offeredGames: 300, keptGames: 180, notKeptGames: 120,
  keepRate: 60, winRateKept: 55, avgEloGainKept: 2, avgEloGainNotKept: -1,
}]});
assert.strictEqual(cardOnly.length, 1);
assert.strictEqual(cardOnly[0].name1, '');
assert.strictEqual(cardOnly[0].name2, 'Cartel');
assert.strictEqual(cardOnly[0].avgEloChange, 2);
assert.strictEqual(cardOnly[0].avgEloNotKept, -1);
assert.strictEqual(cardOnly[0].winRate, 0.55);
assert.strictEqual(cardOnly[0].offeredGames, 300);
assert.strictEqual(cardOnly[0].keepRate, 0.6);

const corporations = context.api.normalizeStandalonePayload({items: [{
  name: 'Ecoline', gameCount: 500, avgEloChange: 0.5, winRate: 0.52,
}]});
assert.strictEqual(corporations.length, 1);
assert.strictEqual(corporations[0].name2, 'Ecoline');
assert.strictEqual(corporations[0].avgEloChange, 0.5);

const played = context.api.normalizePlayedPayload({played: [{
  corporation: 'Inventrix', card: 'Industrial Center', acquiredGames: 40,
  playedGames: 12, notPlayedGames: 28, playRate: 0.3, avgEloPlayed: 1.5,
  avgEloNotPlayed: -0.5, winRatePlayed: 0.58, corporationBaselineElo: 0.4,
}]});
assert.strictEqual(played.length, 1);
assert.strictEqual(played[0].playedGames, 12);
assert.strictEqual(played[0].avgEloNotPlayed, -0.5);
assert.strictEqual(played[0].corporationBaselineElo, 0.4);

const playedByCard = context.api.aggregatePlayedByCard([...played, {
  corporation: 'Ecoline', card: 'Industrial Center', acquiredGames: 60,
  playedGames: 18, notPlayedGames: 42, playRate: 0.3, avgEloPlayed: 3.5,
  avgEloNotPlayed: 1.5, winRatePlayed: 0.62,
}]);
assert.strictEqual(playedByCard.length, 1);
assert.strictEqual(playedByCard[0].corporation, '');
assert.strictEqual(playedByCard[0].acquiredGames, 100);
assert.strictEqual(playedByCard[0].playedGames, 30);
assert.strictEqual(playedByCard[0].notPlayedGames, 70);
assert.strictEqual(playedByCard[0].playRate, 0.3);
assert.strictEqual(playedByCard[0].avgEloPlayed, 2.7);
assert.ok(Math.abs(playedByCard[0].avgEloNotPlayed - 0.7) < 1e-12);
assert.ok(Math.abs(playedByCard[0].winRatePlayed - 0.604) < 1e-12);
const playedCombination = context.api.playedRowAsCombination(playedByCard[0]);
assert.strictEqual(playedCombination.name2, 'Industrial Center');
assert.strictEqual(playedCombination.offeredGames, 100);
assert.strictEqual(playedCombination.gameCount, 30);
assert.strictEqual(playedCombination.notKeptGames, 70);
assert.strictEqual(playedCombination.keepRate, 0.3);
assert.strictEqual(playedCombination.avgEloChange, 2.7);

const draftDetail = context.api.normalizeDraftDetail({data: [{
  stage: 'draft', draftNumber: 3, offered: 200, kept: 150, notKept: 50,
  keepRate: 75, eloKept: 1.2, eloNotKept: -0.4, winRateKept: 0.55,
}]})[0];
assert.strictEqual(draftDetail.generation, 3);
assert.strictEqual(draftDetail.rate, 0.75);
assert.strictEqual(draftDetail.positiveElo, 1.2);

const playedDetail = context.api.normalizePlayedDetail({data: [{
  generation: 4, available: 90, played: 30, notPlayed: 60,
  playRate: 1 / 3, eloPlayed: 2, eloNotPlayed: -1, winRatePlayed: 0.6,
}]})[0];
assert.strictEqual(playedDetail.generation, 4);
assert.strictEqual(playedDetail.positive, 30);
assert.strictEqual(playedDetail.negativeElo, -1);

const restored = context.api.normalizeViewState({
  combinationGeneration: '7', combinationMinimumGames: '100', combinationRows: 100,
  combinationType: 'card-card', combinationSort: 'winRate',
  combinationDirection: 'asc', combinationPage: 5,
  corpCardMode: 'played', selectedDetailCard: 'Sabotage',
});
assert.strictEqual(restored.combinationGeneration, '7');
assert.strictEqual(restored.combinationMinimumGames, '100');
assert.strictEqual(restored.combinationType, 'card-card');
assert.strictEqual(restored.combinationPage, 5);
assert.strictEqual(restored.corpCardMode, 'played');
assert.strictEqual(restored.selectedDetailCard, 'Sabotage');
const fourSearchState = context.api.normalizeViewState({combinationSearch4: 'Saturn', combinationSearch5: 'Ecoline'});
assert.strictEqual(fourSearchState.combinationSearch4, 'Saturn');
assert.strictEqual(fourSearchState.combinationSearch5, 'Ecoline');
const startingView = context.api.normalizeViewState({combinationGeneration: ''});
assert.strictEqual(startingView.combinationGeneration, '');
assert.strictEqual(context.api.normalizeViewState().combinationGeneration, '');
assert.strictEqual(context.api.draftGenerationValue('1'), '');
assert.strictEqual(context.api.draftGenerationValue('2'), '2');
assert.strictEqual(context.api.draftGenerationValue('10'), '10');
assert.strictEqual(context.api.draftGenerationValue('15'), '');
assert.strictEqual(context.api.draftGenerationValue('0'), '');
assert.strictEqual(context.api.playGenerationValue(''), 1);
assert.strictEqual(context.api.playGenerationInputValue(''), '');
assert.strictEqual(context.api.playGenerationInputValue('1'), '1');
assert.strictEqual(context.api.playGenerationInputValue('14'), '14');
assert.strictEqual(context.api.playGenerationInputValue('15'), '');
assert.strictEqual(context.api.normalizeViewState({corpCardMode: 'played', combinationGeneration: '1'}).combinationGeneration, '1');
const exactShuttles = context.api.filterRowsBySearch([
  {name: 'Shuttles'}, {name: 'Immigration Shuttles'},
], row => row.name, 'shuttles');
assert.deepStrictEqual(exactShuttles.map(row => row.name), ['Shuttles']);

const invalidView = context.api.normalizeViewState({
  combinationGeneration: '-1', combinationRows: 17, combinationType: 'bogus', combinationPage: 0,
});
assert.strictEqual(invalidView.combinationGeneration, '');
assert.strictEqual(invalidView.combinationRows, 25);
assert.strictEqual(invalidView.combinationType, 'corp-card');
assert.strictEqual(invalidView.combinationPage, 1);

console.log('Browser data contract OK');
