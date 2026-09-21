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


def _partial_doc(cup, n_rounds, winner, extra_rows=(), **kw):
    """A synthetic partial_rounds/ document: n_rounds rounds the winner led,
    with a field that shrinks to a two-player final like a real cup."""
    # Keep the filler clear of the winner and of anyone the extras already
    # stand for, so an aliased ghost is not also counted as himself.
    taken = {br.normalize_name(winner)}
    taken |= {br.normalize_name(r[0]) for r in extra_rows}
    taken |= {br.normalize_name(v) for v in (kw.get('aliases') or {}).values()}
    roster = [p['name'] for p in br.CUPS[f'COTD {cup}']['players']
              if br.normalize_name(p['name']) not in taken]
    extra = [list(r) for r in extra_rows]
    rounds = {}
    for i in range(n_rounds):
        # last round is the winner plus one, every earlier round one bigger
        filler = roster[:max(0, (n_rounds - i) - len(extra))]
        rows = [[winner, 40.0]] + extra + [[n, 41.0 + j] for j, n in enumerate(filler)]
        rounds[str(i + 1)] = rows
    doc = {'cup': cup, 'source': 'test', 'rounds': rounds}
    doc.update(kw)
    return doc


def _write(tmp_path, doc):
    p = tmp_path / f"cotd_{doc['cup']}.json"
    p.write_text(json.dumps(doc), encoding='utf-8')
    return str(p)


def test_unfinished_reconstruction_is_held_back(tmp_path):
    """An in-progress transcription must never reach the site: with only some
    rounds present, 'led every round' is trivially true and would mint a sweep
    that never happened. COTD 135 really had 15 rounds."""
    result, warn = br.load_partial_cup(_write(tmp_path, _partial_doc(135, 1, 'justMaki')))
    assert result is None
    assert '1 rounds transcribed' in warn and '15' in warn

    # All 15 and it is allowed through, sweep claim and all.
    result, warn = br.load_partial_cup(_write(tmp_path, _partial_doc(135, 15, 'justMaki')))
    assert result is not None and warn is None
    assert result[0]['rounds'] == 15 and result[0]['sweep'] is True


def test_lexer_workbook_vouches_for_a_cup_the_pipeline_never_processed(tmp_path):
    """COTD 138 has no cup_138.json, but Lexer's xlsx records an Elim Round for
    every cup ever run, so the round count is still checkable without the file
    having to declare anything."""
    if br.xlsx_elim_rounds(138)[1] is None:
        pytest.skip('workbooks not on disk (gitignored)')

    result, warn = br.load_partial_cup(_write(tmp_path, _partial_doc(138, 16, 'Kernkob')))
    assert result is not None and warn is None

    result, warn = br.load_partial_cup(_write(tmp_path, _partial_doc(138, 15, 'Kernkob')))
    assert result is None and '15 rounds transcribed' in warn and '16' in warn


def test_complete_flag_is_the_last_resort(monkeypatch, tmp_path):
    """With neither cup_<N>.json nor the workbooks (a fresh clone: both are
    gitignored), the file's own claim is all that is left."""
    monkeypatch.setattr(br, 'xlsx_elim_rounds', lambda num: ({}, None))

    result, warn = br.load_partial_cup(_write(tmp_path, _partial_doc(138, 16, 'Kernkob')))
    assert result is None and 'complete' in warn

    result, warn = br.load_partial_cup(
        _write(tmp_path, _partial_doc(138, 16, 'Kernkob', complete=True)))
    assert result is not None and warn is None


def test_lexer_elimination_order_catches_a_player_racing_after_they_are_out(tmp_path):
    """Somebody Lexer records as knocked out in round R cannot still be racing
    later. This is what would catch a misread name or a mis-numbered round."""
    if not br.xlsx_elim_rounds(138)[0]:
        pytest.skip('workbooks not on disk (gitignored)')
    elims = br.xlsx_elim_rounds(138)[0]
    early = min(elims.items(), key=lambda kv: kv[1])  # someone out in an early round

    doc = _partial_doc(138, 16, 'Kernkob', extra_rows=[[early[0], 45.0]], complete=True)
    result, warn = br.load_partial_cup(_write(tmp_path, doc))
    assert result is not None  # advisory, not fatal
    assert 'eliminated' in warn and early[0] in warn


def test_ghost_account_is_credited_to_the_real_player(tmp_path):
    """COTD 135's `del gaming` is Sterben; the engine's own ghosts export says
    so. Without the alias it would become a phantom player in the aggregates."""
    rows = [['del gaming', 41.0]]
    doc = _partial_doc(135, 15, 'justMaki', extra_rows=rows, aliases={'del gaming': 'Sterben'})
    (cup, raced), warn = br.load_partial_cup(_write(tmp_path, doc))
    assert warn is None
    assert raced['Sterben'] == 15
    assert 'del gaming' not in raced

    # Drop the alias and the name is reported rather than silently counted.
    # Here it also empties the two-player final, so the cup is held back --
    # the point is that the warning names the culprit either way.
    doc.pop('aliases')
    result, warn = br.load_partial_cup(_write(tmp_path, doc))
    assert 'del gaming' in warn and 'aliases' in warn
    if result is not None:
        assert 'del gaming' not in result[1] and 'Sterben' not in result[1]


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
