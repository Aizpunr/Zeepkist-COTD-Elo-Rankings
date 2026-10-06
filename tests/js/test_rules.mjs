// Rule tests for cotd_parser.js on tiny synthetic logs.
//
// Mirrors every case in tests/test_parser_rules.py, plus the places where
// JavaScript's defaults differ from Python's (rounding, sort order, strip).
// Run: node --test tests/js/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const P = createRequire(import.meta.url)(join(repo, 'cotd_parser.js'));

// One COTDTracker log line, terminator included, exactly like the Python L().
const L = msg => '[Info   :COTDTracker] ' + msg + '\n';

function leaderboard(lines, excluded = []) {
  const p = P.parseCupLog(lines, excluded);
  return [p, p.leaderboard.map(x => [x.name, x.timeRaw, x.round, x.pos])];
}

const TIE_LOG = [
  L('Doing eliminations with leaderboard:'),
  L('Player W: Time: 40.0'),
  L('Player X: Time: 41.0'),
  L('Player A: Time: 46.0'),
  L('Doing eliminations with leaderboard:'),
  L('Player W: Time: 40,1'),
  L('Player X: Time: 41,1'),
  L('Player A: Time: 45,5'),
  L('Player B: Time: 44,5'),
  L('Player C: Time: DNF'),
  L('Player D: Time: DNF'),
  L('Eliminating on time: A'),
  L('Eliminating on time: B'),
  L('Eliminating DNF: C'),
  L('Eliminating DNF: D'),
  L('Doing eliminations with leaderboard:'),
  L('Player W: Time: 40,2'),
  L('Player X: Time: 43,0'),
  L('Eliminating on time: X'),
];

const TIE_EXPECTED = [
  ['W', '40,2', null, 1],
  ['X', '43,0', 2, 2],
  ['B', '44,5', 1, 3],
  ['A', '45,5', 1, 4],
  ['D', 'DNF', 1, 5],
  ['C', 'DNF', 1, 5],
];

test('tie rule: finishers distinct, DNFs share the bottom of the round', () => {
  const [p, lb] = leaderboard(TIE_LOG);
  assert.equal(p.winner, 'W');
  assert.equal(p.ambiguous, false);
  assert.deepEqual(lb, TIE_EXPECTED);
  assert.equal(p.nRounds, 3);
});

test('same result from lines with terminators and from split text', () => {
  const [, fromLines] = leaderboard(TIE_LOG);
  const [, crlf] = leaderboard(P.splitLines(TIE_LOG.join('').replace(/\n/g, '\r\n')));
  const [, cr] = leaderboard(P.splitLines(TIE_LOG.join('').replace(/\n/g, '\r')));
  assert.deepEqual(crlf, fromLines);
  assert.deepEqual(cr, fromLines);
});

test('time_ms matches raw and DNF stays DNF', () => {
  const [p] = leaderboard(TIE_LOG);
  const byName = Object.fromEntries(p.leaderboard.map(x => [x.name, x.timeMs]));
  assert.deepEqual(byName, { W: 40200, X: 43000, B: 44500, A: 45500, C: 'DNF', D: 'DNF' });
  assert.equal(p.winnerTimeMs, 40200);
  const payload = P.cupJsonPayload(p, 999, 'Mapper');
  assert.deepEqual(payload.players[0], { pos: 1, name: 'W', time: 40200, round: null });
  assert.deepEqual(payload.players.at(-1), { pos: 5, name: 'C', time: 'DNF', round: 1 });
  assert.equal(payload.cup, 'COTD 999');
  assert.equal(payload.mapper, 'Mapper');
});

test('fastest time can come from the warmup view', () => {
  const [p] = leaderboard(TIE_LOG);
  assert.deepEqual([p.fastestName, p.fastestTime, p.fastestRound], ['W', 40.0, 0]);
});

test('fastest round numbering counts only eliminating rounds', () => {
  const log = [
    L('Doing eliminations with leaderboard:'),
    L('Player W: Time: 50.0'),
    L('Player Y: Time: 51.0'),
    L('Doing eliminations with leaderboard:'),
    L('Player W: Time: 39,9'),
    L('Player Y: Time: 52,0'),
    L('Eliminating on time: Y'),
  ];
  const [p] = leaderboard(log);
  assert.deepEqual([p.fastestName, p.fastestRound], ['W', 1]);
});

test('ambiguous winner is reported, not guessed', () => {
  const log = [
    L('Doing eliminations with leaderboard:'),
    L('Player P: Time: 40,0'),
    L('Player Q: Time: 41,0'),
    L('Player R: Time: DNF'),
    L('Eliminating DNF: R'),
  ];
  const p = P.parseCupLog(log);
  assert.deepEqual(p.candidates, ['P', 'Q']);
  assert.equal(p.winner, null);
  assert.equal(p.ambiguous, true);
  assert.deepEqual(p.leaderboard, []);
});

test('candidates sort by code point like Python, not by UTF-16 unit', () => {
  // U+FF21 (fullwidth A) < U+1D4B1 (script V) by code point, but the astral
  // char is stored as surrogates starting 0xD835, which sorts BEFORE 0xFF21
  // under JavaScript's default sort.
  const astral = '\u{1D4B1}', fullwidth = 'Ａ';
  const log = [
    L('Doing eliminations with leaderboard:'),
    L('Player ' + astral + ': Time: 40,0'),
    L('Player ' + fullwidth + ': Time: 41,0'),
    L('Player R: Time: DNF'),
    L('Eliminating DNF: R'),
  ];
  const p = P.parseCupLog(log);
  assert.deepEqual(p.candidates, [fullwidth, astral]);
  assert.deepEqual([fullwidth, astral].sort(), [astral, fullwidth], 'sanity: default sort differs');
});

test('excluded players are removed, not DNFd', () => {
  const [p, lb] = leaderboard(TIE_LOG, ['A']);
  assert.ok(!lb.map(x => x[0]).includes('A'));
  assert.deepEqual(lb[2], ['B', '44,5', 1, 3]);
  assert.deepEqual(p.warnings, []);
});

test('excluding the winner leaves no candidate', () => {
  const p = P.parseCupLog(TIE_LOG, ['W']);
  assert.deepEqual(p.candidates, []);
  assert.equal(p.winner, null);
  assert.equal(p.ambiguous, false);
});

test('excluded name absent from the log is warned, not fatal', () => {
  const p = P.parseCupLog(TIE_LOG, ['Ghost']);
  assert.equal(p.warnings.length, 1);
  assert.ok(p.warnings[0].startsWith("excluded name 'Ghost' not found in the log"), p.warnings[0]);
  assert.ok(p.warnings[0].includes('\u2014'), 'keeps the em dash of the Python message');
  assert.equal(p.winner, 'W');
});

test('warning quotes a name containing an apostrophe like Python repr', () => {
  const p = P.parseCupLog(TIE_LOG, ["O'Neil"]);
  assert.ok(p.warnings[0].startsWith('excluded name "O\'Neil" not found'), p.warnings[0]);
});

test('pre-filtered input is accepted', () => {
  const onlyTracker = TIE_LOG.filter(l => l.includes('COTDTracker'));
  const noisy = ['[Info   :BepInEx] Loading plugin\n', ...TIE_LOG, '[Message: Chainloader] done\n'];
  assert.deepEqual(P.parseCupLog(onlyTracker).leaderboard, P.parseCupLog(noisy).leaderboard);
});

for (const [raw, expected] of [
  ['45,05365', 45054],
  ['43.34747', 43347],
  ['DNF', 'DNF'],
  [45054, 45054],
  [null, null],
]) {
  test('timeToMs(' + JSON.stringify(raw) + ')', () => {
    assert.equal(P.timeToMs(raw), expected);
  });
}

test('parse errors', () => {
  assert.throws(() => P.parseCupLog([]), e => e instanceof P.ParseError && /No COTDTracker lines/.test(e.message));
  assert.throws(() => P.parseCupLog([L('Plugin COTDTracker is loaded!')]),
    e => e instanceof P.ParseError && /No elimination rounds/.test(e.message));
});

// ── Python-vs-JavaScript primitives ──

test('pyRound is half-to-even like Python round()', () => {
  assert.equal(P.pyRound(2.5), 2);
  assert.equal(P.pyRound(3.5), 4);
  assert.equal(P.pyRound(-2.5), -2);
  assert.equal(P.pyRound(45053.65), 45054);
  assert.equal(P.pyRound(0.49999999999999994), 0);
  assert.equal(Math.round(2.5), 3, 'sanity: Math.round differs');
});

test('pyStrip strips Python whitespace, which trim() does not', () => {
  assert.equal(P.pyStrip('\x1f Zed \x85'), 'Zed');
  assert.equal(P.pyStrip('﻿Zed'), '﻿Zed', 'BOM is not whitespace to Python');
  assert.notEqual('\x1fZed'.trim(), 'Zed', 'sanity: trim differs');
});

test('names with Python-only whitespace parse the same as Python', () => {
  const log = [
    L('Doing eliminations with leaderboard:'),
    L('Player Zed\x1f: Time: 41,0'),
    L('Player Amy: Time: DNF'),
    L('Eliminating DNF: Amy'),
  ];
  const p = P.parseCupLog(log);
  assert.equal(p.winner, 'Zed');
});

test('pyFloat accepts what float() accepts and rejects the rest', () => {
  assert.equal(P.pyFloat('45.5'), 45.5);
  assert.equal(P.pyFloat(' 45.5 '), 45.5);
  assert.equal(P.pyFloat('1_000.5'), 1000.5);
  assert.equal(P.pyFloat('.5'), 0.5);
  assert.equal(P.pyFloat('5.'), 5);
  assert.equal(P.pyFloat('inf'), Infinity);
  for (const bad of ['', '12abc', '0x10', '1__0', 'DNF', '4.5.1']) {
    assert.throws(() => P.pyFloat(bad), e => e instanceof P.PyValueError, bad);
  }
});

test('a non-numeric non-DNF time raises in the fastest scan, like Python', () => {
  const log = [
    L('Doing eliminations with leaderboard:'),
    L('Player W: Time: 40,0'),
    L('Player A: Time: 45,0'),
    L('Player B: Time: ???'),
    L('Eliminating on time: A'),
    L('Eliminating on time: B'),
  ];
  assert.throws(() => P.parseCupLog(log), e => e instanceof P.PyValueError);
});

test('splitLines follows text-mode readlines', () => {
  assert.deepEqual(P.splitLines(''), []);
  assert.deepEqual(P.splitLines('a\r\nb\rc\nd'), ['a', 'b', 'c', 'd']);
  assert.deepEqual(P.splitLines('a\n'), ['a']);
  assert.deepEqual(P.splitLines('a\n\nb\n'), ['a', '', 'b']);
  assert.deepEqual(P.splitLines('a b'), ['a b'], 'U+2028 is not a line break for readlines');
});

test('decodeBytes keeps a BOM like open(encoding="utf-8")', () => {
  const bytes = new Uint8Array([0xef, 0xbb, 0xbf, 0x41]);
  assert.equal(P.decodeBytes(bytes), '﻿A');
});

test('winner names with regex metacharacters are escaped', () => {
  const w = '[KBW]K.e+rn(kob)?';
  const log = [
    L('Doing eliminations with leaderboard:'),
    L('Player ' + w + ': Time: 40,0'),
    L('Player Amy: Time: DNF'),
    L('Eliminating DNF: Amy'),
    L('Doing eliminations with leaderboard:'),
    L('Player ' + w + ': Time: 39,5'),
    L('Player Bo: Time: 44,0'),
    L('Eliminating on time: Bo'),
  ];
  const p = P.parseCupLog(log);
  assert.equal(p.winner, w);
  assert.equal(p.winnerTimeRaw, '39,5');
});

test('a player named __proto__ does not break name bookkeeping', () => {
  const log = [
    L('Doing eliminations with leaderboard:'),
    L('Player __proto__: Time: 40,0'),
    L('Player constructor: Time: 41,0'),
    L('Eliminating on time: constructor'),
  ];
  const p = P.parseCupLog(log);
  assert.equal(p.winner, '__proto__');
  assert.deepEqual(p.leaderboard.map(x => x.name), ['__proto__', 'constructor']);
});

test('namedPlayers lists every timed name, code-point sorted', () => {
  assert.deepEqual(P.namedPlayers(TIE_LOG), ['A', 'B', 'C', 'D', 'W', 'X']);
});
