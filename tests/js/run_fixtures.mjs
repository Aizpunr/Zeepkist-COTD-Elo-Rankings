// Golden fixtures for the JavaScript parser port.
//
// Every tests/fixtures/cotd_N/ must parse, through cotd_parser.js, to exactly
// the bytes of its expected.json (newline style normalized), the same lock
// tests/test_parser_golden.py puts on cotd_parser.py.
//
// Usage: node tests/js/run_fixtures.mjs     (exit 0 = all match)
import { createRequire } from 'node:module';
import { readFileSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, '..', '..');
const P = createRequire(import.meta.url)(join(repo, 'cotd_parser.js'));

const fixturesDir = join(repo, 'tests', 'fixtures');
const dirs = readdirSync(fixturesDir, { withFileTypes: true })
  .filter(d => d.isDirectory() && /^cotd_\d+$/.test(d.name))
  .map(d => d.name)
  .sort();

let failures = 0;

function fail(name, msg) {
  failures += 1;
  console.log(`FAIL ${name}: ${msg}`);
}

function firstDiff(a, b) {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) if (a[i] !== b[i]) return i;
  return a.length === b.length ? -1 : n;
}

if (!dirs.length) {
  console.log('FAIL: no fixtures under tests/fixtures');
  process.exit(1);
}

for (const name of dirs) {
  const dir = join(fixturesDir, name);
  const n = Number(name.split('_')[1]);
  const manifest = JSON.parse(readFileSync(join(dir, 'manifest.json'), 'utf8'));
  const lines = P.splitLines(P.decodeBytes(readFileSync(join(dir, `cotd_${n}.log`))));
  const expectedText = readFileSync(join(dir, 'expected.json')).toString('utf8');
  const expected = JSON.parse(expectedText);
  const exclude = new Set(manifest.exclude);

  let parsed;
  try {
    parsed = P.parseCupLog(lines, exclude);
  } catch (e) {
    fail(name, `threw ${e.name}: ${e.message}`);
    continue;
  }
  if (parsed.ambiguous) { fail(name, `ambiguous: ${JSON.stringify(parsed.candidates)}`); continue; }
  if (parsed.winner !== expected.players[0].name) {
    fail(name, `winner ${JSON.stringify(parsed.winner)} != ${JSON.stringify(expected.players[0].name)}`);
    continue;
  }

  const payload = P.cupJsonPayload(parsed, manifest.cup, manifest.mapper);
  const keys = Object.keys(payload).join(',');
  if (keys !== 'cup,cup_num,mapper,players') { fail(name, `payload key order ${keys}`); continue; }
  const badPlayer = payload.players.find(p => Object.keys(p).join(',') !== 'pos,name,time,round');
  if (badPlayer) { fail(name, `player key order ${Object.keys(badPlayer).join(',')}`); continue; }
  const leaked = payload.players.filter(p => exclude.has(p.name)).map(p => p.name);
  if (leaked.length) { fail(name, `excluded names in the field: ${JSON.stringify(leaked)}`); continue; }

  const rendered = JSON.stringify(payload, null, 2);
  const want = expectedText.replace(/\r\n/g, '\n');
  if (rendered !== want) {
    const at = firstDiff(rendered, want);
    const ctx = s => JSON.stringify(s.slice(Math.max(0, at - 60), at + 60));
    fail(name, `rendered JSON differs at char ${at}\n  got:  ${ctx(rendered)}\n  want: ${ctx(want)}`);
    continue;
  }
  console.log(`ok ${name} (${payload.players.length} players, winner ${parsed.winner})`);
}

if (failures) {
  console.log(`${failures} of ${dirs.length} fixture(s) FAILED`);
  process.exit(1);
}
console.log(`all ${dirs.length} fixtures match`);
