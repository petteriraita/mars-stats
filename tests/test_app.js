'use strict';

const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync(new URL('../app.js', `file://${__filename}`), 'utf8');
const definitions = source.split("$$('[data-page-link]')")[0];
const context = {Intl, URLSearchParams, console};
vm.createContext(context);
vm.runInContext(`${definitions}\nthis.api = {normalizeStartingPayload, normalizeCombinationPayload, metricWithMinimum, signed};`, context);

const starting = context.api.normalizeStartingPayload({data: [{
  cardName: 'Cartel', offeredGames: 20, keptGames: 10, notKeptGames: 10,
  keepRate: 50, avgEloGainOffered: 1, avgEloGainKept: 4,
  avgEloGainNotKept: -2, avgEloDeltaOffered: 0.75,
  avgEloDeltaKept: 3.75, avgEloDeltaNotKept: -2.25,
}]});
assert.strictEqual(starting.length, 1);
assert.strictEqual(starting[0].name, 'Cartel');
assert.strictEqual(starting[0].eloOffered, 1);
assert.strictEqual(starting[0].eloKept, 4);
assert.strictEqual(starting[0].eloNotKept, -2);
assert.strictEqual(context.api.signed(null), '—');
assert.strictEqual(context.api.signed(-2), '−2.00');

const sparse = context.api.normalizeStartingPayload({data: [{
  cardName: 'Sparse card', offeredGames: 105, keptGames: 5, notKeptGames: 100,
  keepRate: 4.8, avgEloGainOffered: 2, avgEloGainKept: 20, avgEloGainNotKept: 1,
}]})[0];
assert.strictEqual(sparse.eloOffered, 2);
assert.strictEqual(sparse.eloKept, null);
assert.strictEqual(sparse.eloNotKept, 1);
assert.strictEqual(context.api.metricWithMinimum(99, 9), null);
assert.strictEqual(context.api.metricWithMinimum(99, 10), 99);

const combinations = context.api.normalizeCombinationPayload({combinations: [{
  name1: 'Cartel', name2: 'Earth Office', gameCount: 100, winRate: 0.55,
  avgEloChange: 4, baseline1Elo: 0.5, baseline2Elo: 0.25,
  lift1: 3.5, lift2: 3.75, totalLift: 3.25,
}]});
assert.strictEqual(combinations.length, 1);
assert.strictEqual(combinations[0].name1, 'Cartel');
assert.strictEqual(combinations[0].avgEloChange, 4);
assert.strictEqual(combinations[0].totalLift, 3.25);

console.log('Browser data contract OK');
