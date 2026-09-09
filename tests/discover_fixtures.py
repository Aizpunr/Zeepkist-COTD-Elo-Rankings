"""discover_fixtures.py: replay saved cup logs through cotd_parser and report
which cups reproduce their committed cup_<N>.json exactly.

    python tests/discover_fixtures.py [N ...]

For every cup that has both `cup logs/cotd_N.log` and `cup_N.json`, the log
is parsed with an exclude set and the resulting payload is compared to the
committed JSON as a dict. The exclude set comes from
`tests/fixtures/cotd_N/manifest.json` when that fixture exists, otherwise it
starts as {mapper} and is grown by inference: any name the parser emits that
the JSON lacks must have been excluded when the cup was processed (mapper
under another handle, testers, people who left before round 1). Up to four
inference passes are tried.

One line per cup:
  MATCH  N  exclude=[...]            parser output == committed JSON
  DIFF   N  exclude=[...]  first differing rows
  NO-UNIQUE-WINNER  N                the log has 0 or 2+ never-eliminated players

Exit status is 1 only if a cup that HAS a manifest fails to MATCH (those are
the committed golden fixtures); discovery-only cups never fail the run.
"""
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from cotd_parser import ParseError, cup_json_payload, parse_cup_log_file  # noqa: E402

CUP_LOGS = os.path.join(REPO, 'cup logs')
FIXTURES = os.path.join(HERE, 'fixtures')
MAX_INFER = 4


def candidate_cups():
    nums = []
    for fn in os.listdir(CUP_LOGS):
        m = re.fullmatch(r'cotd_(\d+)\.log', fn)
        if m and os.path.exists(os.path.join(REPO, f'cup_{m.group(1)}.json')):
            nums.append(int(m.group(1)))
    return sorted(nums)


def load_manifest(n):
    path = os.path.join(FIXTURES, f'cotd_{n}', 'manifest.json')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return None


def rows(payload):
    return [(p['name'], p['time'], p['round'], p['pos']) for p in payload['players']]


def first_diffs(a, b, k=2):
    out = []
    for x, y in zip(rows(a), rows(b)):
        if x != y:
            out.append((x, y))
            if len(out) == k:
                break
    if not out and len(a['players']) != len(b['players']):
        out.append((f"{len(a['players'])} players", f"{len(b['players'])} players"))
    return out


def replay(n, exclude):
    log = os.path.join(CUP_LOGS, f'cotd_{n}.log')
    with open(os.path.join(REPO, f'cup_{n}.json'), encoding='utf-8') as f:
        expected = json.load(f)
    parsed = parse_cup_log_file(log, exclude)
    if parsed.winner is None:
        return 'NO-UNIQUE-WINNER', parsed, expected, None
    payload = cup_json_payload(parsed, n, expected['mapper'])
    return ('MATCH' if payload == expected else 'DIFF'), parsed, expected, payload


def discover(n):
    manifest = load_manifest(n)
    with open(os.path.join(REPO, f'cup_{n}.json'), encoding='utf-8') as f:
        mapper = json.load(f)['mapper']
    exclude = set(manifest['exclude']) if manifest else {mapper}
    status = parsed = expected = payload = None
    for _ in range(MAX_INFER + 1):
        try:
            status, parsed, expected, payload = replay(n, exclude)
        except ParseError as e:
            return {'cup': n, 'status': f'PARSE-ERROR {e}', 'exclude': exclude,
                    'missing': [], 'diffs': [], 'manifest': manifest is not None}
        if status != 'DIFF' or manifest:
            break
        extra = {p['name'] for p in payload['players']} - {p['name'] for p in expected['players']}
        if not extra:
            break
        exclude |= extra
    missing = [w for w in parsed.warnings if 'not found in the log' in w]
    diffs = first_diffs(payload, expected) if status == 'DIFF' else []
    return {'cup': n, 'status': status, 'exclude': exclude, 'missing': missing,
            'diffs': diffs, 'manifest': manifest is not None}


def main(argv):
    wanted = [int(a) for a in argv] if argv else candidate_cups()
    failed_manifested = 0
    counts = {}
    for n in wanted:
        r = discover(n)
        counts[r['status'].split()[0]] = counts.get(r['status'].split()[0], 0) + 1
        excl = ','.join(sorted(r['exclude']))
        tag = ' [fixture]' if r['manifest'] else ''
        line = f"{r['status']:<18} {n:<4} exclude=[{excl}]{tag}"
        if r['missing']:
            line += f"  excluded-but-absent={len(r['missing'])}"
        print(line)
        for got, exp in r['diffs']:
            print(f"    parser={got}")
            print(f"    json  ={exp}")
        if r['manifest'] and r['status'] != 'MATCH':
            failed_manifested += 1
    print()
    print('summary:', ', '.join(f'{k}={v}' for k, v in sorted(counts.items())))
    if failed_manifested:
        print(f'FAIL: {failed_manifested} committed fixture(s) no longer reproduce')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
