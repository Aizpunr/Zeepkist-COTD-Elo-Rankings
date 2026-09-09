"""Golden-file tests: every fixture under tests/fixtures/cotd_N/ must parse
to exactly its committed expected.json.

A fixture is a byte-exact subset of a real game log plus the cup file the
pipeline produced from it (see tests/make_fixture.py). If a parser change
breaks one of these on purpose, regenerate the fixture with make_fixture.py
--force and explain the rule change in the commit.
"""
import glob
import json
import os

import pytest

from cotd_parser import cup_json_payload, parse_cup_log

FIXTURE_DIRS = sorted(glob.glob(os.path.join(os.path.dirname(__file__), 'fixtures', 'cotd_*')))


def load(fixture_dir):
    n = int(os.path.basename(fixture_dir).split('_')[1])
    with open(os.path.join(fixture_dir, 'manifest.json'), encoding='utf-8') as f:
        manifest = json.load(f)
    with open(os.path.join(fixture_dir, f'cotd_{n}.log'), encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    with open(os.path.join(fixture_dir, 'expected.json'), 'rb') as f:
        expected_text = f.read().decode('utf-8')
    return manifest, lines, expected_text


@pytest.mark.parametrize('fixture_dir', FIXTURE_DIRS, ids=[os.path.basename(d) for d in FIXTURE_DIRS])
def test_fixture_reproduces_expected_json(fixture_dir):
    manifest, lines, expected_text = load(fixture_dir)
    expected = json.loads(expected_text)
    exclude = set(manifest['exclude'])

    parsed = parse_cup_log(lines, exclude)
    assert not parsed.ambiguous, parsed.candidates
    assert parsed.winner == expected['players'][0]['name']

    payload = cup_json_payload(parsed, manifest['cup'], manifest['mapper'])
    assert payload == expected

    names = {p['name'] for p in payload['players']}
    assert not (names & exclude), 'an excluded name is in the field'

    # Serialization lock: the exact bytes new_cup.py writes (indent=2,
    # ensure_ascii=False, no trailing newline), newline style normalized.
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    assert rendered == expected_text.replace('\r\n', '\n')


def test_fixtures_exist():
    assert FIXTURE_DIRS, 'no fixtures under tests/fixtures; run tests/make_fixture.py'
