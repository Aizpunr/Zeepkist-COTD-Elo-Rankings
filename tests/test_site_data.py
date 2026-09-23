"""The site's data files must be whole.

alldata.json is written twice: elo_engine.py creates it with its own five
keys, then build_altrank.py merges in standard, trueskill and cupDates.
Running the engine on its own therefore leaves a file that looks fine, loads
fine, and is missing half of itself. That shipped once, on 2026-09-22, and
other repos read cupDates from it.
"""
import json
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXPECTED = {
    'alldata.json': ['weighted', 'weighted_pure', 'season_2026', 'glicko2', 'glicko2_pure',
                     'standard', 'standard_pure', 'trueskill', 'trueskill_pure', 'cupDates'],
    'rising.json': ['current_cup', 'lookback_cup', 'lookback_3m', 'lookback_cups',
                    'min_rating', 'weighted', 'weighted_pure', 'standard', 'standard_pure'],
}


@pytest.mark.parametrize('name', sorted(EXPECTED))
def test_every_section_survived_the_second_writer(name):
    path = os.path.join(REPO, name)
    if not os.path.exists(path):
        pytest.skip(f'{name} not built')
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    missing = [k for k in EXPECTED[name] if k not in data]
    assert not missing, (
        f'{name} is missing {missing}. elo_engine.py rewrites it from scratch, so '
        f'run build_altrank.py to merge the rest back in.')


def test_cup_dates_reach_the_newest_cup():
    """cupDates is the section other repos read, and the one that vanishes."""
    path = os.path.join(REPO, 'alldata.json')
    if not os.path.exists(path):
        pytest.skip('alldata.json not built')
    with open(path, encoding='utf-8') as f:
        dates = json.load(f).get('cupDates') or {}
    assert dates, 'cupDates is empty'
    with open(os.path.join(REPO, 'cups.json'), encoding='utf-8') as f:
        cups = json.load(f)
    newest = max(int(c['id'].split()[-1]) for c in cups
                 if c['id'].startswith('COTD ') and c['id'].split()[-1].isdigit())
    have = {int(''.join(ch for ch in k if ch.isdigit()) or 0) for k in dates}
    assert newest in have, f'cupDates stops short of COTD {newest}'
