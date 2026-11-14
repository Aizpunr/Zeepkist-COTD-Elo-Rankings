"""stability_history.json is the cup-by-cup version of elo_stability.json.

build_stability_history.py carries its own copy of the stability maths (it has
to run the calculation as of past cups), so the newest snapshot is checked
against the file elo_stability.py publishes. If the two ever drift, this fails.
"""
import json
import os

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name):
    path = os.path.join(BASE, name)
    if not os.path.exists(path):
        pytest.skip(f'{name} not built')
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def test_newest_snapshot_matches_the_published_stability_points():
    hist = _load('stability_history.json')
    now = _load('elo_stability.json')
    assert hist['through'] == now['parameters']['current_cup']

    want = {r['name']: r['stability_point'] for r in now['results']
            if r['recent_cups'] >= hist['min_cups']}
    got = hist['cups'][str(hist['through'])]['p']
    assert set(got) == set(want)
    worst = max(abs(got[n] - want[n]) for n in want)
    assert worst <= 0.2, f'stability points differ by up to {worst}'


def test_every_cup_since_the_first_full_window_has_a_snapshot():
    hist = _load('stability_history.json')
    cups = sorted(int(c) for c in hist['cups'])
    assert cups[0] == hist['window']
    assert cups == list(range(cups[0], hist['through'] + 1))
    for c in hist['cups'].values():
        assert c['t'] > 1500 and c['p'], 'a snapshot with no top-10 average or no players'
