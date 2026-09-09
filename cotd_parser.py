"""cotd_parser.py: pure parser for COTDTracker mod logs.

Turns the `[Info   :COTDTracker] ...` lines of a Zeepkist BepInEx LogOutput.log
into a finished cup leaderboard. This is the logic that used to live inline in
new_cup.py; it was extracted so it can be unit-tested against saved logs and
called by other front ends (the planned upload/confirm flow) without going
through the command line.

Design rules:
  - No I/O except parse_cup_log_file(), no printing, no sys.exit. Callers
    decide what to do with warnings and with an ambiguous winner.
  - Behavior is a line-for-line port of the original new_cup.py parser,
    including its quirks (see comments). Do not "improve" the rules here
    without regenerating the golden fixtures under tests/.

Format notes (from the mod's output):
  - A round begins with "Doing eliminations with leaderboard:" followed by
    "Player <name>: Time: <t>" lines (t is the raw token: '45,05365' on a
    comma-locale PC, '43.34747' on a dot-locale PC, or 'DNF').
  - Eliminations are "Eliminating on time: <name>" / "Eliminating DNF: <name>".
  - The first leaderboard with no eliminations is the discovery/warmup view
    (round 0); round 1 is the first leaderboard that eliminates someone.
"""
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

TRACKER_TAG = 'COTDTracker'

_RE_PLAYER_TIME = re.compile(r'Player (.+?): Time: (.+)')
_RE_PLAYER_NAMED = re.compile(r'Player (.+?): Time:')
_RE_ELIMINATED = re.compile(r'Eliminating (?:DNF|on time): (.+)')
_RE_HAS_ELIM = re.compile(r'Eliminating (?:DNF|on time):')


class ParseError(ValueError):
    """The log does not contain a parseable cup."""


@dataclass(frozen=True)
class ParsedPlayer:
    name: str            # raw in-game name, tag and all
    time_raw: str        # exact log token in the elimination round, or 'DNF'
    round: Optional[int] # elimination round (1-based); None for the winner
    pos: int             # final position (DNFs of one round share a position)


@dataclass
class ParsedCup:
    leaderboard: list = field(default_factory=list)   # list[ParsedPlayer]; empty unless exactly one winner
    candidates: list = field(default_factory=list)    # sorted names never eliminated and not excluded
    winner: Optional[str] = None                      # candidates[0] iff exactly one candidate
    winner_time_raw: Optional[str] = None
    fastest_time: Optional[float] = None              # seconds, full log precision
    fastest_name: Optional[str] = None
    fastest_round: Optional[int] = None               # 0 == warmup leaderboard
    n_rounds: int = 0                                 # leaderboards in the log, warmup included
    warnings: list = field(default_factory=list)      # human-readable, non-fatal

    @property
    def ambiguous(self) -> bool:
        return len(self.candidates) > 1


def filter_tracker_lines(lines: Iterable[str]) -> list:
    """Keep only the mod's lines. Idempotent, so a pre-filtered fixture is
    valid input."""
    return [l for l in lines if TRACKER_TAG in l]


def split_rounds(tracker_lines: Iterable[str]) -> list:
    """Group the player/elimination lines by leaderboard."""
    rounds = []
    current_round = []
    for line in tracker_lines:
        if 'Doing eliminations with leaderboard' in line:
            if current_round:
                rounds.append(current_round)
            current_round = []
        elif 'Eliminating ' in line or 'Player ' in line:
            current_round.append(line)
    if current_round:
        rounds.append(current_round)
    return rounds


def parse_cup_log(lines: Iterable[str], excluded: Iterable[str] = ()) -> ParsedCup:
    """Parse a cup from log lines (raw or already filtered to tracker lines).

    `excluded` are raw in-game names to drop from the field entirely (mapper,
    testers, people who left before round 1). They are removed, never DNF'd.
    """
    excluded = set(excluded)
    lines = filter_tracker_lines(lines)
    if not lines:
        raise ParseError("No COTDTracker lines found in log file.")

    rounds = split_rounds(lines)
    if not rounds:
        raise ParseError("No elimination rounds found in log.")

    cup = ParsedCup(n_rounds=len(rounds))

    # Build elimination order. For each eliminated player keep the time shown
    # in their elimination round (or 'DNF'); the dnf flag decides the tie rule.
    # display_time is ONLY the elim round's own entry: no fallback to an
    # earlier round's time.
    elim_order = []
    actual_round = 0
    for rnd in rounds:
        player_times = {}
        eliminated_names = []
        for line in rnd:
            m = _RE_PLAYER_TIME.search(line)
            if m:
                name = m.group(1).strip()
                time_str = m.group(2).strip()
                player_times[name] = time_str
            m2 = _RE_ELIMINATED.search(line)
            if m2:
                name = m2.group(1).strip()
                if name not in eliminated_names:
                    eliminated_names.append(name)
        if not eliminated_names:
            continue
        actual_round += 1
        for name in eliminated_names:
            if name not in excluded:
                elim_round_time = player_times.get(name, 'DNF')
                dnf = (elim_round_time == 'DNF')
                elim_order.append((name, elim_round_time, actual_round, dnf))

    # Everyone the tracker ever named.
    all_named = set()
    for rnd in rounds:
        for line in rnd:
            m = _RE_PLAYER_NAMED.search(line)
            if m:
                all_named.add(m.group(1).strip())

    # An excluded name that never appears excluded nobody: either they did
    # not play, or the raw name is wrong (COTD 152: mapper passed as "Victor"
    # while the log had "[MMM]Victor", so he was counted as a player).
    for name in sorted(excluded):
        if name not in all_named:
            cup.warnings.append(
                f"excluded name {name!r} not found in the log — "
                f"either they didn't play, or this isn't their exact raw in-game name.")

    # Winner = named but never eliminated. More than one means a mid-cup
    # disconnect the tracker never eliminated, or a truncated log; the caller
    # must not guess.
    elim_set = {e[0] for e in elim_order}
    cup.candidates = sorted(n for n in all_named if n not in elim_set and n not in excluded)
    if len(cup.candidates) != 1:
        return cup
    winner = cup.candidates[0]
    cup.winner = winner

    winner_time = None
    pat = re.compile(r'Player ' + re.escape(winner) + r': Time: (.+)')
    for line in reversed(lines):
        m = pat.search(line)
        if m:
            winner_time = m.group(1).strip()
            break
    cup.winner_time_raw = winner_time

    # Leaderboard. Within one elimination round, finishers get distinct
    # positions ordered by their elim-round time (faster = better); DNFs of
    # that round all tie at the bottom of the round.
    elim_order.reverse()
    leaderboard = [ParsedPlayer(winner, winner_time, None, 1)]
    pos = 2
    i = 0
    while i < len(elim_order):
        rnd = elim_order[i][2]
        group = []
        while i < len(elim_order) and elim_order[i][2] == rnd:
            group.append(elim_order[i])
            i += 1
        finishers = []
        dnfs = []
        for name, display_time, r, dnf in group:
            if dnf:
                dnfs.append((name, display_time, r))
            else:
                try:
                    t = float(str(display_time).replace(',', '.'))
                    finishers.append((name, display_time, r, t))
                except (ValueError, TypeError):
                    dnfs.append((name, display_time, r))
        finishers.sort(key=lambda x: x[3])
        for name, display_time, r, _ in finishers:
            leaderboard.append(ParsedPlayer(name, display_time, r, pos))
            pos += 1
        if dnfs:
            dnf_pos = pos
            for name, display_time, r in dnfs:
                leaderboard.append(ParsedPlayer(name, display_time, r, dnf_pos))
            pos += len(dnfs)
    cup.leaderboard = leaderboard

    # Fastest time over every leaderboard, warmup included (round 0). Quirk
    # kept from the original: excluded players are NOT filtered out here, and a
    # non-numeric token other than 'DNF' would raise (the mod never emits one).
    fastest_time = None
    fastest_name = None
    fastest_round = None
    actual_round = 0
    for rnd in rounds:
        has_elim = any(_RE_HAS_ELIM.search(line) for line in rnd)
        if has_elim:
            actual_round += 1
        rnd_num = actual_round if has_elim else 0
        for line in rnd:
            m = _RE_PLAYER_TIME.search(line)
            if m:
                name = m.group(1).strip()
                time_str = m.group(2).strip()
                if time_str != 'DNF':
                    t = float(time_str.replace(',', '.'))
                    if fastest_time is None or t < fastest_time:
                        fastest_time = t
                        fastest_name = name
                        fastest_round = rnd_num
    cup.fastest_time = fastest_time
    cup.fastest_name = fastest_name
    cup.fastest_round = fastest_round
    return cup


def parse_cup_log_file(path: str, excluded: Iterable[str] = ()) -> ParsedCup:
    with open(path, encoding='utf-8', errors='replace') as f:
        return parse_cup_log(f.readlines(), excluded)


def cup_json_payload(parsed: ParsedCup, cup_num: int, mapper: str) -> dict:
    """The cup_<N>.json document (same shape new_cup.py has always written)."""
    return {
        'cup': f'COTD {cup_num}',
        'cup_num': cup_num,
        'mapper': mapper,
        'players': [
            {'pos': p.pos, 'name': p.name, 'time': p.time_raw, 'round': p.round}
            for p in parsed.leaderboard
        ],
    }
