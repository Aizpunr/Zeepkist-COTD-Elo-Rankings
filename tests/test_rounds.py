"""build_rounds.py: the round-by-round view of a cup must agree with the
leaderboard the pipeline published for the same log.

The golden fixtures are byte-exact COTDTracker excerpts, so they exercise the
same parse the real logs get without depending on the gitignored `cup logs/`.
"""
import json
import os

import pytest

import build_rounds as br

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')
CUPS = sorted(d for d in os.listdir(FIX) if d.startswith('cotd_'))


def load(cup_dir):
    d = os.path.join(FIX, cup_dir)
    with open(os.path.join(d, 'manifest.json'), encoding='utf-8') as f:
        manifest = json.load(f)
    with open(os.path.join(d, 'expected.json'), encoding='utf-8') as f:
        expected = json.load(f)
    with open(os.path.join(d, f"cotd_{manifest['cup']}.log"), encoding='utf-8') as f:
        lines = f.readlines()
    return manifest, expected, lines


def metrics_for(cup_dir):
    manifest, expected, lines = load(cup_dir)
    excluded = set(manifest['exclude'])
    boards = [(r, [(n, t) for n, t in b if n not in excluded])
              for r, b in br.round_boards(lines)]
    winner = br.normalize_name(
        next(p['name'] for p in expected['players'] if p['pos'] == 1))
    return manifest, expected, boards, br.round_metrics(boards, winner)


@pytest.mark.parametrize('cup_dir', CUPS)
def test_round_count_matches_the_published_leaderboard(cup_dir):
    _, expected, _, m = metrics_for(cup_dir)
    last = max(p['round'] for p in expected['players'] if p['round'])
    assert m['rounds'] == last
    assert len(m['leaders']) == m['rounds']
    assert len(m['ranks']) == m['rounds']


@pytest.mark.parametrize('cup_dir', CUPS)
def test_the_winner_leads_the_final_round(cup_dir):
    # The final is two players and the slower one goes out, so whoever is left
    # is by definition the fastest of that round.
    _, _, _, m = metrics_for(cup_dir)
    assert m['leaders'][-1] == m['winner']


@pytest.mark.parametrize('cup_dir', CUPS)
def test_led_is_consistent(cup_dir):
    _, _, _, m = metrics_for(cup_dir)
    assert 1 <= m['led'] <= m['rounds']
    assert m['led'] == sum(1 for l in m['leaders'] if l == m['winner'])
    assert m['sweep'] == (m['led'] == m['rounds'])
    assert all(r is None or r >= 1 for r in m['ranks'])
    assert m['worst'] == max([r for r in m['ranks'] if r] or [0])


@pytest.mark.parametrize('cup_dir', CUPS)
def test_dropped_rounds_match_the_leaders(cup_dir):
    """Every round the winner did not lead is recorded once, with the margin
    they lost it by when their own time for that round is known."""
    _, _, _, m = metrics_for(cup_dir)
    expected = [i + 1 for i, l in enumerate(m['leaders']) if l and l != m['winner']]
    assert [d['round'] for d in m['dropped']] == expected
    assert len(m['dropped']) == m['rounds'] - m['led']
    for d in m['dropped']:
        assert d['to'] == m['leaders'][d['round'] - 1]
        assert d['to'] != m['winner']
        # A positive margin: the winner was strictly slower that round.
        assert d['margin'] is None or d['margin'] > 0


def test_margin_is_the_gap_to_the_round_leader():
    def board(entries, rnd):
        return (rnd, entries)

    boards = [
        board([('W', 41.592), ('A', 41.589)], 1),   # W loses by 0.003
        board([('W', 40.0), ('A', 41.0)], 2),       # W leads
    ]
    m = br.round_metrics(boards, 'W')
    assert m['led'] == 1 and m['rounds'] == 2
    assert m['dropped'] == [{'round': 1, 'to': 'A', 'margin': 0.003}]

    # The winner DNF'd the round they lost: no time, so no margin to report.
    m = br.round_metrics([board([('W', None), ('A', 41.0)], 1)], 'W')
    assert m['dropped'] == [{'round': 1, 'to': 'A', 'margin': None}]


@pytest.mark.parametrize('cup_dir', CUPS)
def test_excluded_players_never_appear(cup_dir):
    manifest, _, boards, _ = metrics_for(cup_dir)
    seen = {n for _, board in boards for n, _t in board}
    assert not (seen & set(manifest['exclude']))


@pytest.mark.parametrize('cup_dir', CUPS)
def test_field_shrinks_every_round(cup_dir):
    # Each elimination round has strictly fewer racers than the one before, and
    # the last one is the two finalists.
    _, _, boards, _ = metrics_for(cup_dir)
    sizes = [len(b) for r, b in boards if r > 0]
    assert all(a > b for a, b in zip(sizes, sizes[1:])), sizes
    assert sizes[-1] == 2, sizes


def test_a_sweep_is_detected():
    """Synthetic: one name on top of every board is a sweep, one slip is not."""
    def board(names, rnd):
        return (rnd, [(n, 40.0 + i) for i, n in enumerate(names)])

    swept = [board(['W', 'a', 'b'], 1), board(['W', 'a'], 2)]
    m = br.round_metrics(swept, 'W')
    assert m['sweep'] and m['led'] == 2 and m['worst'] == 1 and m['changes'] == 0

    slipped = [board(['a', 'W', 'b'], 1), board(['W', 'a'], 2)]
    m = br.round_metrics(slipped, 'W')
    assert not m['sweep'] and m['led'] == 1 and m['worst'] == 2 and m['changes'] == 1

    # The warmup board (round 0) is never an elimination round.
    warm = [(0, [('a', 39.0), ('W', 41.0)])] + swept
    m = br.round_metrics(warm, 'W')
    assert m['sweep'] and m['rounds'] == 2 and m['warmup'] is False
