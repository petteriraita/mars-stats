'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync(new URL('../app.js', `file://${__filename}`), 'utf8');
const definitions = source.split("$$('[data-page-link]')")[0];
const context = {Intl, URLSearchParams, console};
vm.createContext(context);
vm.runInContext(`${definitions}\nthis.api = {normalizeStartingPayload, normalizeCombinationPayload, normalizeViewState, metricWithMinimum, signed};`, context);

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

const sparse = context.api.normalizeStartingPayload({data: [{
  cardName: 'Sparse card', offeredGames: 105, keptGames: 5, notKeptGames: 100,
  keepRate: 4.8, avgEloGainOffered: 2, avgEloGainKept: 20, avgEloGainNotKept: 1,
}]})[0];
assert.strictEqual(sparse.eloOffered, 2);
assert.strictEqual(sparse.eloKept, null);
assert.strictEqual(sparse.eloNotKept, 1);
assert.strictEqual(context.api.metricWithMinimum(99, 99), null);
assert.strictEqual(context.api.metricWithMinimum(99, 100), 99);

const combinations = context.api.normalizeCombinationPayload({combinations: [{
  name1: 'Cartel', name2: 'Earth Office', gameCount: 100, winRate: 0.55,
  avgEloChange: 4, baseline1Elo: 0.5, baseline2Elo: 0.25,
  lift1: 3.5, lift2: 3.75, totalLift: 3.25,
}]});
assert.strictEqual(combinations.length, 1);
assert.strictEqual(combinations[0].name1, 'Cartel');
assert.strictEqual(combinations[0].avgEloChange, 4);
assert.strictEqual(combinations[0].totalLift, 3.25);

const restored = context.api.normalizeViewState({
  startingGeneration: '4', combinationGeneration: '7', startingRows: 50,
  combinationRows: 100, startingSort: 'offered', startingDirection: 'asc',
  currentPage: 3, combinationType: 'card-card', combinationSort: 'winRate',
  combinationDirection: 'asc', combinationPage: 5, keepCardsInView: true,
  lockedCardOrder: ['Cartel', 'AI Central'],
});
assert.strictEqual(restored.startingGeneration, '4');
assert.strictEqual(restored.combinationGeneration, '7');
assert.strictEqual(restored.startingRows, 50);
assert.strictEqual(restored.currentPage, 3);
assert.strictEqual(restored.combinationType, 'card-card');
assert.strictEqual(restored.combinationPage, 5);
assert.strictEqual(restored.keepCardsInView, true);

const invalidView = context.api.normalizeViewState({
  startingGeneration: '-1', startingRows: 17, startingSort: 'bogus',
  combinationType: 'bogus', combinationPage: 0,
});
assert.strictEqual(invalidView.startingGeneration, '');
assert.strictEqual(invalidView.startingRows, 25);
assert.strictEqual(invalidView.startingSort, 'eloKept');
assert.strictEqual(invalidView.combinationType, 'corp-prelude');
assert.strictEqual(invalidView.combinationPage, 1);

console.log('Browser data contract OK');
