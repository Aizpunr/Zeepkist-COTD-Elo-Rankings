"""make_fixture.py: create a golden test fixture from a processed cup.

    python tests/make_fixture.py N --exclude name1,name2 [--note "..."]

Writes tests/fixtures/cotd_N/ with:
  cotd_N.log      the COTDTracker lines of `cup logs/cotd_N.log`, byte-exact
                  (binary subset, CRLF preserved; ~20-35 KB instead of 250 KB+)
  expected.json   a copy of the committed cup_N.json
  manifest.json   {cup, mapper, map, exclude, source_log, filter, note}

`--exclude` is the FULL set that was passed to the parser when the cup was
processed, mapper included (tests/discover_fixtures.py infers it). The
fixture is validated IN MEMORY first: the trimmed log is parsed with that
exclude set and must reproduce expected.json exactly. Nothing is written
unless it does, so this script never has to delete a bad fixture.
"""
import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from cotd_parser import cup_json_payload, parse_cup_log  # noqa: E402

TAG = b'COTDTracker'


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('cup', type=int)
    ap.add_argument('--exclude', default='', help='comma-separated raw names, mapper included')
    ap.add_argument('--note', default='')
    ap.add_argument('--force', action='store_true', help='overwrite an existing fixture')
    a = ap.parse_args(argv)
    n = a.cup
    exclude = sorted(x.strip() for x in a.exclude.split(',') if x.strip())

    src_log = os.path.join(REPO, 'cup logs', f'cotd_{n}.log')
    src_json = os.path.join(REPO, f'cup_{n}.json')
    for p in (src_log, src_json):
        if not os.path.exists(p):
            print(f'ERROR: missing {p}')
            return 1

    with open(src_log, 'rb') as f:
        raw_lines = f.read().split(b'\n')
    kept = [l for l in raw_lines if TAG in l]
    trimmed = b'\n'.join(kept)
    if kept and raw_lines and raw_lines[-1] == b'':
        trimmed += b'\n'

    with open(src_json, encoding='utf-8') as f:
        expected = json.load(f)

    # Validate in memory before touching the filesystem.
    text_lines = trimmed.decode('utf-8', errors='replace').splitlines(keepends=True)
    parsed = parse_cup_log(text_lines, exclude)
    if parsed.winner is None:
        print(f'ERROR: no unique winner with exclude={exclude}: candidates={parsed.candidates}')
        return 1
    payload = cup_json_payload(parsed, n, expected['mapper'])
    if payload != expected:
        print(f'ERROR: fixture would NOT reproduce cup_{n}.json with exclude={exclude}')
        for got, exp in zip(payload['players'], expected['players']):
            if got != exp:
                print(f'  first difference: parser={got}  json={exp}')
                break
        print('  hint: run tests/discover_fixtures.py to infer the exclude set')
        return 1

    meta_path = os.path.join(REPO, 'cup_meta.json')
    map_name = None
    if os.path.exists(meta_path):
        with open(meta_path, encoding='utf-8') as f:
            map_name = json.load(f).get(f'COTD {n}', {}).get('map')

    out_dir = os.path.join(HERE, 'fixtures', f'cotd_{n}')
    if os.path.exists(out_dir) and not a.force:
        print(f'ERROR: {out_dir} exists (use --force to overwrite)')
        return 1
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f'cotd_{n}.log'), 'wb') as f:
        f.write(trimmed)
    with open(src_json, 'rb') as f_in, open(os.path.join(out_dir, 'expected.json'), 'wb') as f_out:
        f_out.write(f_in.read())
    manifest = {
        'cup': n,
        'mapper': expected['mapper'],
        'map': map_name,
        'exclude': exclude,
        'source_log': f'cup logs/cotd_{n}.log',
        'filter': 'COTDTracker',
        'note': a.note,
    }
    with open(os.path.join(out_dir, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f'fixture cotd_{n}: {len(kept)} tracker lines ({len(trimmed) // 1024} KB), '
          f'{len(expected["players"])} players, winner {parsed.winner}, exclude={exclude}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
