// The Worker keeps every submission on record, including resends of a file it
// already has. Runs the real submit-worker/src/index.js against an in-memory KV.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {webcrypto} from 'node:crypto';

const source = readFileSync(new URL('../../submit-worker/src/index.js', import.meta.url), 'utf8');
const {default: worker} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
if (!globalThis.crypto) globalThis.crypto = webcrypto;
const originalFetch = globalThis.fetch;
globalThis.fetch = async () => Response.json({success: true, hostname: 'localhost'});

class KV {
  data = new Map();
  async get(k) { return this.data.get(k)?.value ?? null; }
  async put(k, value, metadata) { this.data.set(k, {value, metadata}); }
}
const ORIGIN = 'http://localhost:8000';
const env = () => ({SUBMISSIONS: new KV(), TURNSTILE_SECRET: 'test-placeholder', POLLER_TOKEN: 'test-placeholder',
  ALLOWED_ORIGINS: ORIGIN, TURNSTILE_HOSTNAMES: 'localhost'});

async function submit(e, cup, body = 'one') {
  const form = new FormData();
  const log = `[Info   :COTDTracker] Doing eliminations with leaderboard:\n[Info   :COTDTracker] Player ${body}: Time: 40.0\n`;
  form.set('file', new Blob([log]), 'LogOutput.log');
  for (const [k, v] of Object.entries({cup: String(cup), map: 'Some Map', mapper: '[X]Mapper', exclude: '[]',
    date: new Date().toISOString().slice(0, 10), submitter: 'tester', 'cf-turnstile-response': 'fake'})) form.set(k, v);
  const r = await worker.fetch(new Request('https://example.test/submit',
    {method: 'POST', headers: {Origin: ORIGIN}, body: form}), e);
  assert.equal(r.status, 200, await r.clone().text());
  return r.json();
}

try {
  const e = env();
  const first = await submit(e, 167);
  assert.equal(first.status, 'received');

  // Same file, same cup: its own record, plain duplicate, bytes not stored again.
  const again = await submit(e, 167);
  assert.equal(again.status, 'duplicate');
  assert.notEqual(again.id, first.id);
  assert.equal(again.same_file_as, first.id);
  assert.equal(e.SUBMISSIONS.data.has('log:' + again.id), false);

  // Same file sent as another cup: flagged for review.
  const other = await submit(e, 168);
  assert.equal(other.status, 'duplicate');

  const st = await (await worker.fetch(new Request('https://example.test/status'), e)).json();
  const byId = Object.fromEntries(st.submissions.map(s => [s.id, s]));
  assert.equal(st.submissions.length, 3);
  assert.equal(byId[again.id].note, 'same file as ' + first.id);
  assert.equal(byId[other.id].note, 'REVIEW: same file as ' + first.id + ', which was sent as COTD 167');
  assert.equal(byId[other.id].same_file_as, first.id);

  // A different file is a new submission as before.
  assert.equal((await submit(e, 167, 'two')).status, 'received');

  // Duplicates never reach the poller.
  const pending = await (await worker.fetch(new Request('https://example.test/pending',
    {headers: {Authorization: 'Bearer test-placeholder'}}), e)).json();
  assert.deepEqual(pending.submissions.map(s => s.status), ['received', 'received']);
  console.log('worker ok');
} finally {
  globalThis.fetch = originalFetch;
}
