"""Unit tests for the parsing rules in cotd_parser, on tiny synthetic logs.

These pin the rules that have been wrong before (the tie rule was
over-merged between 2026-04-07 and 2026-04-12) so a future edit cannot
change them silently. Golden-file tests cover real cups; these cover the
edge cases a real cup may not contain.
"""
import pytest

from cotd_parser import ParseError, cup_json_payload, parse_cup_log, time_to_ms


def L(msg):
    """One COTDTracker log line."""
    return f'[Info   :COTDTracker] {msg}\n'


def leaderboard(lines, excluded=()):
    p = parse_cup_log(lines, excluded)
    return p, [(x.name, x.time_raw, x.round, x.pos) for x in p.leaderboard]


# Warmup view (no eliminations), then R1 eliminates A and B on time (B faster)
# plus C and D as DNF, then R2 eliminates X. W is never eliminated.
TIE_LOG = [
    L('Doing eliminations with leaderboard:'),
    L('Player W: Time: 40.0'),
    L('Player X: Time: 41.0'),
    L('Player A: Time: 46.0'),
    L('Doing eliminations with leaderboard:'),
    L('Player W: Time: 40,1'),
    L('Player X: Time: 41,1'),
    L('Player A: Time: 45,5'),
    L('Player B: Time: 44,5'),
    L('Player C: Time: DNF'),
    L('Player D: Time: DNF'),
    L('Eliminating on time: A'),
    L('Eliminating on time: B'),
    L('Eliminating DNF: C'),
    L('Eliminating DNF: D'),
    L('Doing eliminations with leaderboard:'),
    L('Player W: Time: 40,2'),
    L('Player X: Time: 43,0'),
    L('Eliminating on time: X'),
]


def test_tie_rule_finishers_distinct_dnfs_share_bottom_of_round():
    p, lb = leaderboard(TIE_LOG)
    assert p.winner == 'W' and not p.ambiguous
    assert lb == [
        ('W', '40,2', None, 1),   # winner: last time seen for W
        ('X', '43,0', 2, 2),      # R2 finisher
        ('B', '44,5', 1, 3),      # R1 finishers ordered by elim-round time
        ('A', '45,5', 1, 4),
        ('D', 'DNF', 1, 5),       # R1 DNFs tie at the bottom of the round, listed in
        ('C', 'DNF', 1, 5),       # reverse elimination order (elim_order is reversed whole)
    ]
    assert p.n_rounds == 3  # warmup + 2 elimination rounds


def test_time_ms_matches_raw_and_dnf_stays_dnf():
    p, _ = leaderboard(TIE_LOG)
    by_name = {x.name: x.time_ms for x in p.leaderboard}
    assert by_name == {'W': 40200, 'X': 43000, 'B': 44500, 'A': 45500, 'C': 'DNF', 'D': 'DNF'}
    assert p.winner_time_ms == 40200
    payload = cup_json_payload(p, 999, 'Mapper')
    assert payload['players'][0] == {'pos': 1, 'name': 'W', 'time': 40200, 'round': None}
    assert payload['players'][-1] == {'pos': 5, 'name': 'C', 'time': 'DNF', 'round': 1}
    assert payload['cup'] == 'COTD 999' and payload['mapper'] == 'Mapper'


def test_fastest_time_can_come_from_the_warmup_view():
    p, _ = leaderboard(TIE_LOG)
    # W's 40.0 in the warmup leaderboard is the fastest token in the whole log.
    assert (p.fastest_name, p.fastest_time, p.fastest_round) == ('W', 40.0, 0)


def test_fastest_time_round_numbering_counts_only_eliminating_rounds():
    log = [
        L('Doing eliminations with leaderboard:'),
        L('Player W: Time: 50.0'),
        L('Player Y: Time: 51.0'),
        L('Doing eliminations with leaderboard:'),
        L('Player W: Time: 39,9'),
        L('Player Y: Time: 52,0'),
        L('Eliminating on time: Y'),
    ]
    p, _ = leaderboard(log)
    assert (p.fastest_name, p.fastest_round) == ('W', 1)


def test_ambiguous_winner_is_reported_not_guessed():
    log = [
        L('Doing eliminations with leaderboard:'),
        L('Player P: Time: 40,0'),
        L('Player Q: Time: 41,0'),
        L('Player R: Time: DNF'),
        L('Eliminating DNF: R'),
    ]
    p = parse_cup_log(log)
    assert p.candidates == ['P', 'Q']   # sorted, deterministic
    assert p.winner is None and p.ambiguous
    assert p.leaderboard == []


def test_excluded_players_are_removed_not_dnfd():
    p, lb = leaderboard(TIE_LOG, excluded={'A'})
    names = [x[0] for x in lb]
    assert 'A' not in names
    assert lb[2] == ('B', '44,5', 1, 3)   # B keeps position 3, nobody shifts up past the gap
    assert p.warnings == []


def test_excluding_the_winner_leaves_no_candidate():
    p = parse_cup_log(TIE_LOG, excluded={'W'})
    assert p.candidates == [] and p.winner is None and not p.ambiguous


def test_excluded_name_absent_from_log_is_warned_not_fatal():
    p = parse_cup_log(TIE_LOG, excluded={'Ghost'})
    assert len(p.warnings) == 1
    assert p.warnings[0].startswith("excluded name 'Ghost' not found in the log")
    assert p.winner == 'W'


def test_pre_filtered_input_is_accepted():
    only_tracker = [l for l in TIE_LOG if 'COTDTracker' in l]
    noisy = ['[Info   :BepInEx] Loading plugin\n'] + TIE_LOG + ['[Message: Chainloader] done\n']
    assert parse_cup_log(only_tracker).leaderboard == parse_cup_log(noisy).leaderboard


@pytest.mark.parametrize('raw, expected', [
    ('45,05365', 45054),
    ('43.34747', 43347),
    ('DNF', 'DNF'),
    (45054, 45054),
    (None, None),
])
def test_time_to_ms(raw, expected):
    assert time_to_ms(raw) == expected


def test_parse_errors():
    with pytest.raises(ParseError, match='No COTDTracker lines'):
        parse_cup_log([])
    with pytest.raises(ParseError, match='No elimination rounds'):
        parse_cup_log([L('Plugin COTDTracker is loaded!')])
