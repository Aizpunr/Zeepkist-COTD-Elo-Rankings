"""cup_links.json feeds the icons on the cups table: the map's ZeepCentraal page
and the cup's videos. The file is partly hand-edited, so its shape is checked
here, along with the rules build_cup_links.py uses to match a video to a cup.
"""
import datetime
import json
import os
import re
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import build_cup_links as links  # noqa: E402

D = datetime.date


def _load(name):
    path = os.path.join(BASE, name)
    if not os.path.exists(path):
        pytest.skip(f'{name} not built')
    with open(path, encoding='utf-8') as f:
        return json.load(f)


# ── the committed file ──────────────────────────────────────
def test_every_link_belongs_to_a_cup_and_has_the_right_shape():
    data = _load('cup_links.json')
    cups = {c['id'] for c in _load('cups.json')}
    for cup, entry in data.items():
        assert cup in cups, f'{cup} is not a cup in cups.json'
        assert set(entry) <= {'zc', 'lexer', 'sandals'}, f'{cup} has an unknown key'
        # '' means "checked, there is none"
        if entry.get('zc'):
            assert re.fullmatch(r'[0-9A-F]{32}', entry['zc']), f'{cup}: {entry["zc"]} is not a ZeepCentraal level id'
        for ch in ('lexer', 'sandals'):
            if entry.get(ch):
                assert re.fullmatch(r'[\w-]{11}', entry[ch]), f'{cup}: {entry[ch]} is not a YouTube video id'


def test_no_video_is_linked_to_two_cups():
    data = _load('cup_links.json')
    seen = {}
    for cup, entry in data.items():
        for ch in ('lexer', 'sandals'):
            vid = entry.get(ch)
            if vid:
                assert vid not in seen, f'{vid} is linked to both {seen[vid]} and {cup}'
                seen[vid] = cup


def test_linked_videos_come_from_the_right_playlist():
    data = _load('cup_links.json')
    videos = _load('cup_videos.json')
    for cup, entry in data.items():
        for ch in ('lexer', 'sandals'):
            vid = entry.get(ch)
            if vid and vid in videos:
                assert videos[vid]['ch'] == ch, f"{cup}: {vid} is in {videos[vid]['ch']}'s playlist, not {ch}'s"


# ── the matching rules ──────────────────────────────────────
CUPS = [
    {'id': 'COTD 1', 'date': D(2025, 1, 4), 'mapper': '[TTR] Tigerplaysonpc'},
    {'id': 'COTD 2', 'date': D(2025, 1, 11), 'mapper': 'Diabler'},
    {'id': 'Troll COTD 1', 'date': None, 'mapper': 'Lexer'},
    {'id': 'COTD 3', 'date': D(2025, 1, 25), 'mapper': 'JobW'},
]


def _video(vid, date, title='A Zeepkist Cup of the Day', desc=''):
    return {'id': vid, 'title': title, 'date': date, 'desc': desc}


def test_a_video_goes_to_the_latest_cup_before_it():
    matched, review = links.match_videos(CUPS, [_video('a', '2025-01-04'), _video('b', '2025-01-12')])
    assert matched == {'COTD 1': 'a', 'COTD 2': 'b'}
    assert review == []


def test_a_video_too_long_after_any_cup_is_left_for_review():
    matched, review = links.match_videos(CUPS, [_video('a', '2025-01-18')])
    assert matched == {}
    assert review[0][0] == 'a' and 'COTD 2 was 7 days earlier' in review[0][1]


def test_a_cup_number_in_the_description_is_used_when_no_cup_is_near_the_date():
    v = _video('a', '2025-01-20', desc='All results (this is COTD 3): link')
    matched, review = links.match_videos(CUPS, [v])
    assert matched == {'COTD 3': 'a'} and review == []


def test_a_cup_number_that_disagrees_with_the_date_goes_to_review():
    # Either the number is a stray one or our cup date is wrong: a person decides.
    v = _video('a', '2025-01-12', desc='All results (this is COTD 1): link')
    matched, review = links.match_videos(CUPS, [v])
    assert matched == {} and 'names COTD 1 but its date points at COTD 2' in review[0][1]


def test_two_different_cup_numbers_in_a_description_are_ignored():
    v = _video('a', '2025-01-12', desc='After COTD 1 last week, COTD 2 is here')
    matched, _ = links.match_videos(CUPS, [v])
    assert matched == {'COTD 2': 'a'}


def test_sandals_thanks_line_is_read_as_the_mapper():
    v = _video('a', '2025-01-11', desc="Thanks to Butter for making this week's map.")
    matched, review = links.match_videos(CUPS, [v])
    assert matched == {} and 'map by Butter' in review[0][1]


def test_a_stated_troll_cup_is_matched_without_a_date():
    v = _video('a', '2025-01-19', desc='(this is Troll COTD 1)')
    matched, _ = links.match_videos(CUPS, [v])
    assert matched == {'Troll COTD 1': 'a'}


def test_troll_videos_are_never_matched_by_date():
    v = _video('a', '2025-01-12', title='Racing Backwards in a Zeepkist (Troll) Cup of the Day!')
    matched, review = links.match_videos(CUPS, [v])
    assert matched == {} and review[0][0] == 'a'


def test_stroll_and_non_troll_are_regular_cups():
    # Both are real: 'This Was No Leisurely "Stroll"...' and '(non-troll) cup of the day map'.
    a = _video('a', '2025-01-04', title='This Was No Leisurely "Stroll" in this Zeepkist Cup of the Day!')
    b = _video('b', '2025-01-12', desc='Possibly the most difficult (non-troll) cup of the day map')
    matched, review = links.match_videos(CUPS, [a, b])
    assert matched == {'COTD 1': 'a', 'COTD 2': 'b'} and review == []


def test_a_mixed_playlist_needs_the_mapper_named():
    # Sandals' playlist also holds Eggy Cup and Author Time Hunt videos.
    plain = _video('a', '2025-01-04', title='The Fastest Egg in the Cup', desc='EGGY CUP on Friday nights')
    named = _video('b', '2025-01-11', desc="Thanks to Diabler for making this week's map.")
    matched, review = links.match_videos(CUPS, [plain, named], need_mapper=True)
    assert matched == {'COTD 2': 'b'}
    assert review[0][0] == 'a' and 'names no mapper' in review[0][1]


def test_skipped_videos_in_the_cache_are_not_linked():
    data = _load('cup_links.json')
    videos = _load('cup_videos.json')
    linked = {entry[ch] for entry in data.values() for ch in ('lexer', 'sandals') if entry.get(ch)}
    assert not [vid for vid, v in videos.items() if v.get('skip') and vid in linked]


def test_two_videos_for_one_cup_go_to_review():
    matched, review = links.match_videos(CUPS, [_video('a', '2025-01-04'), _video('b', '2025-01-05')])
    assert matched == {}
    assert sorted(v for v, _ in review) == ['a', 'b']


def test_a_description_naming_another_mapper_goes_to_review():
    v = _video('a', '2025-01-11', desc='A fast COTD map by Butter!')
    matched, review = links.match_videos(CUPS, [v])
    assert matched == {} and 'map by Butter' in review[0][1]


def test_a_description_naming_the_cups_mapper_is_accepted_despite_the_clan_tag():
    v = _video('a', '2025-01-04', desc='Zeepkist Cup of the Day! Map by Tigerplaysonpc')
    matched, review = links.match_videos(CUPS, [v])
    assert matched == {'COTD 1': 'a'} and review == []
