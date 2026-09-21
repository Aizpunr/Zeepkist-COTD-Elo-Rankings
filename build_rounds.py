"""
build_rounds.py — round-by-round control stats for the Clean Sweeps cool-stat.

Every saved COTDTracker log prints the WHOLE field, sorted by time, before each
elimination ("Doing eliminations with leaderboard:"). The pipeline only uses
those blocks to work out who got eliminated and throws the ordering away. This
script keeps it, so we can say who was actually leading each round.

A CLEAN SWEEP = the cup winner was first in every elimination round of that cup.

Coverage: cups with a saved mod log (COTD 136 onward), plus any cup in
partial_rounds/ hand-reconstructed from leaderboard screenshots (currently
just 138, the one log-era cup whose log was lost). Everything before 136 can
never be reconstructed: Lexer's xlsx records an elimination round and an
elimination time, never a survivor's time. Historic sweeps found by watching
the VODs go in sweeps_manual.json by hand and are merged here, flagged with
their source.

Output: rounds.json, consumed by sweeps.html.
"""
import glob
import json
import os
import re
import sys
from collections import Counter

base = os.path.dirname(os.path.abspath(__file__))
def _p(f): return os.path.join(base, f)

from cotd_parser import filter_tracker_lines, split_rounds
import cup_paths
from elo_engine import CANONICAL, XLSX_FILES

LOG_DIR = _p('cup logs')
MANUAL = _p('sweeps_manual.json')
PARTIAL_DIR = _p('partial_rounds')

# Same alias resolution as build_fastest.py, so names match across stat pages.
NAME_MAP = {a: c for c, aliases in CANONICAL.items() for a in aliases}

def normalize_name(name):
    if name in NAME_MAP:
        return NAME_MAP[name]
    stripped = re.sub(r'^\[.*?\]\s*', '', name).strip()
    return NAME_MAP.get(stripped, stripped)


RE_PLAYER = re.compile(r'Player (.+?): Time: (.+)')
RE_HAS_ELIM = re.compile(r'Eliminating (?:DNF|on time):')


def round_boards(lines):
    """[(round_no, [(raw_name, seconds or None), ...]), ...] in log order.

    round_no 0 is the discovery/warmup board (a leaderboard that eliminates
    nobody); elimination rounds are numbered 1..n, the same numbering the rest
    of the pipeline uses.
    """
    out = []
    n = 0
    for rnd in split_rounds(filter_tracker_lines(lines)):
        has_elim = any(RE_HAS_ELIM.search(l) for l in rnd)
        if has_elim:
            n += 1
        board = []
        for line in rnd:
            m = RE_PLAYER.search(line)
            if m:
                tok = m.group(2).strip()
                board.append((m.group(1).strip(),
                              None if tok == 'DNF' else float(tok.replace(',', '.'))))
        out.append((n if has_elim else 0, board))
    return out


def round_metrics(boards, winner):
    """The per-cup numbers, from already filtered boards. Pure: no files.

    `boards` is round_boards() output with the non-participants already
    dropped; `winner` is the canonical name of the player who won the cup.
    """
    elim = [(r, b) for r, b in boards if r > 0]
    leaders, ranks, dropped = [], [], []
    for rnd_no, board in elim:
        # Board position breaks a tie, never the name. Both the log and the
        # game rank on the full float and print a rounded time, so two rows can
        # show the same number without being tied, and the order they are
        # printed in is the only thing that still knows which was faster.
        finishers = sorted((t, i, n) for i, (n, t) in enumerate(board) if t is not None)
        order = [normalize_name(n) for _, _, n in finishers]
        lead = order[0] if order else None
        leaders.append(lead)
        # A player who DNF'd or was not on the board has no meaningful rank.
        ranks.append(order.index(winner) + 1 if winner in order else None)
        if lead and lead != winner:
            # The rounds standing between this cup and a clean sweep, and how
            # much the eventual winner lost each one by. The margin needs the
            # winner's own time for that round, which a screenshot may not show.
            wt = next((t for t, _, n in finishers if normalize_name(n) == winner), None)
            dropped.append({
                'round': rnd_no,
                'to': lead,
                'margin': round(wt - finishers[0][0], 5) if wt is not None else None,
            })

    seq = [l for l in leaders if l]
    warmup = next((b for r, b in boards if r == 0), [])
    warm_fin = sorted((t, i, n) for i, (n, t) in enumerate(warmup) if t is not None)
    return {
        'winner': winner,
        'rounds': len(elim),
        'led': sum(1 for l in leaders if l == winner),
        'sweep': bool(elim) and all(l == winner for l in leaders),
        'worst': max([x for x in ranks if x] or [0]),
        'changes': sum(1 for a, b in zip(seq, seq[1:]) if a != b),
        'leaders': leaders,
        'ranks': ranks,
        'dropped': dropped,
        # Led the discovery board too, when the log has one with times on it.
        'warmup': bool(warm_fin) and normalize_name(warm_fin[0][2]) == winner,
    }


# ------------------------------------------------- Lexer's workbook as a check

_ELIM_CACHE = {}

def xlsx_elim_rounds(num):
    """{canonical name: elimination round} for COTD <num>, from Lexer's xlsx.

    The workbook records an Elim Round for every player of every cup ever run,
    which is the only round-level fact that exists for cups with no mod log. It
    cannot say who LED a round, but it does say how many rounds there were and
    who went out in each, so it can check a screenshot reconstruction.

    The winner has no elimination round and is absent from the mapping. Returns
    ({} , None) when the workbooks are not on disk, since they are gitignored.
    """
    if num in _ELIM_CACHE:
        return _ELIM_CACHE[num]
    import openpyxl
    out, last = {}, None
    for fname in XLSX_FILES:
        path = _p(fname)
        if not os.path.exists(path):
            continue
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        try:
            for sheet in wb.worksheets:
                grid = [list(r) for r in sheet.iter_rows(values_only=True)]
                for ri, row in enumerate(grid):
                    for ci, val in enumerate(row):
                        if not (isinstance(val, str) and val.strip() == f'COTD {num}'):
                            continue
                        # The block's header sits a few rows under its title.
                        for hr in range(ri, min(ri + 5, len(grid))):
                            for hc in range(max(0, ci - 3), min(ci + 6, len(grid[hr]))):
                                if str(grid[hr][hc]).strip() != 'Position':
                                    continue
                                for dr in range(hr + 1, len(grid)):
                                    cells = grid[dr]
                                    if hc + 3 >= len(cells) or cells[hc + 1] is None:
                                        break
                                    rnd = cells[hc + 3]
                                    if isinstance(rnd, (int, float)):
                                        out[normalize_name(str(cells[hc + 1]))] = int(rnd)
                                        last = max(last or 0, int(rnd))
                                if out:
                                    _ELIM_CACHE[num] = (out, last)
                                    return _ELIM_CACHE[num]
        finally:
            wb.close()
    _ELIM_CACHE[num] = (out, last)
    return _ELIM_CACHE[num]


def elim_round_count(num, warnings):
    """How many elimination rounds COTD <num> had, from the elimination records.

    A sweep found by watching a VOD comes with a winner and nothing else, but
    "led every round" reads better as "13 of 13", and that number is already in
    the workbook: the last round anybody was eliminated in is the final. Checked
    against the 28 cups that have both a mod log and a workbook block, it agrees
    on every one. The single disagreement is COTD 134, whose block this repo
    wrote itself with a round numbering that counts the discovery round, and
    that block is recognisable because nobody in it went out in round 1. Return
    None rather than a number that is off by one.
    """
    elim, last = xlsx_elim_rounds(num)
    if not last:
        return None
    if 1 not in set(elim.values()):
        warnings.append(f'COTD {num}: the elimination records have nobody going out in round 1, '
                        f'so their round numbering is suspect and the round count is left blank')
        return None
    return last


# ---------------------------------------------------------------- cup context

with open(_p('cups.json'), encoding='utf-8') as f:
    CUPS = {c['id']: c for c in json.load(f)}


def cup_context(num):
    """(field filter, winner, cup row) for COTD <num>.

    The field filter drops everyone the cup was processed WITHOUT (mapper,
    testers, people who left before round 1) so the round boards match the
    published leaderboard. cup_<N>.json holds the raw in-game names, which is an
    exact match against the log; where it is missing (COTD 136) we fall back to
    matching normalized names against the cups.json roster.
    """
    row = CUPS.get(f'COTD {num}')
    if not row or not row.get('players'):
        return None, None, None
    path = cup_paths.cup_json_path(num, base)
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            doc = json.load(f)
        raw = {p['name'] for p in doc['players']}
        winner = next((p['name'] for p in doc['players'] if p['pos'] == 1), None)
        return (lambda name: name in raw), normalize_name(winner), row
    roster = {normalize_name(p['name']) for p in row['players']}
    winner = next((p['name'] for p in row['players'] if p['pos'] == 1), None)
    return (lambda name: normalize_name(name) in roster), normalize_name(winner), row


def analyze(num, lines):
    keep, winner, row = cup_context(num)
    if keep is None:
        return None, f'COTD {num}: not in cups.json, skipped'
    if winner is None:
        return None, f'COTD {num}: no winner in the leaderboard, skipped'

    boards = [(r, [(n, t) for n, t in b if keep(n)]) for r, b in round_boards(lines)]
    elim = [(r, b) for r, b in boards if r > 0]
    if not elim:
        return None, f'COTD {num}: no elimination rounds in the log, skipped'

    cup = {
        'cup': f'COTD {num}',
        'num': num,
        'map': row.get('map') or '',
        'date': row.get('date') or '',
        'field': row.get('lobby_size') or len(row['players']),
    }
    cup.update(round_metrics(boards, winner))
    cup['src'] = 'log'
    # Everyone who raced at least one round, for the per-player denominators.
    raced = Counter()
    for _, board in elim:
        for n, _t in board:
            raced[normalize_name(n)] += 1
    return (cup, raced), None


def load_partial_cup(path):
    """A hand-reconstructed cup from partial_rounds/ (see its README).

    The file is deliberately bare: {"cup": N, "rounds": {"1": [[name, time], ...]}}
    so transcribing a screenshot is one paste. Everything else is derived or
    checked here, and round_metrics() then treats each round's rows as that
    round's board, exactly like a log's leaderboard block minus whoever was off
    screen.
    """
    with open(path, encoding='utf-8') as f:
        doc = json.load(f)
    num = doc['cup']
    keep, winner, cup_row = cup_context(num)
    if winner is None:
        return None, f'partial_rounds/cotd_{num}.json: COTD {num} not in cups.json, skipped'
    roster = {normalize_name(p['name']) for p in cup_row['players']}

    # Raw in-game names that the rankings file under a different name: ghost
    # accounts above all (COTD 135's `del gaming` is Sterben, and the engine's
    # own `ghosts` export says so). Kept per cup instead of in CANONICAL, which
    # five other repos text-parse and which deliberately keeps ghosts separate.
    aliases = doc.get('aliases') or {}

    boards, unknown = [], Counter()
    for rnd_no, rows in sorted(doc['rounds'].items(), key=lambda kv: int(kv[0])):
        board = []
        for entry in rows:
            raw, t = entry[0], (entry[1] if len(entry) > 1 else None)
            if not raw:
                continue  # illegible in the screenshot, not a real entry
            name = aliases.get(raw, raw)
            # Anyone not in the published leaderboard (the mapper, someone who
            # left before round 1) is dropped, exactly as the log path does via
            # cup_context's filter. A name that lands here by accident -- a
            # misread, an unmapped ghost -- gets counted and reported, so it
            # cannot quietly become a phantom player in the aggregates.
            if not keep(name) and normalize_name(name) not in roster:
                unknown[raw] += 1
                continue
            board.append((name, None if t in (None, 'DNF') else float(t)))
        boards.append((int(rnd_no), board))

    # Diagnosed before the completeness gate: an unmapped name can shrink a
    # round enough to trip the gate, and "wrong number of rounds" would then
    # hide the thing you actually need to fix.
    unknown_msg = ''
    if unknown:
        detail = ', '.join(f'{n!r} x{k}' for n, k in unknown.most_common())
        unknown_msg = (f'not in the published COTD {num} leaderboard, dropped from the rounds: '
                       f'{detail}. Check for a misread name or a ghost account needing an '
                       f'"aliases" entry')

    def _stop(why):
        return None, f'partial_rounds/cotd_{num}.json: ' + '; '.join(filter(None, [why, unknown_msg]))

    elim = [(r, b) for r, b in boards if r > 0]
    if not elim:
        # A scaffold with its metadata filled in and no rounds yet is a normal
        # state to leave a transcription in, so say where it stands.
        target = elim_round_count(num, [])
        return _stop(f'0 of {target} rounds transcribed' if target else 'no rounds')

    # A reconstruction in progress must never reach the site. With only some of
    # the rounds transcribed, "the winner led every round" is trivially true for
    # whatever is there so far, which would mint a sweep that never happened.
    # The real round count comes from cup_<N>.json (the runner-up's elimination
    # round) when that file exists; otherwise the file has to declare itself.
    expected = None
    cj = cup_paths.cup_json_path(num, base)
    if os.path.exists(cj):
        with open(cj, encoding='utf-8') as f:
            expected = max((p['round'] for p in json.load(f)['players'] if p['round']),
                           default=None)
    # Lexer's workbook has an Elim Round for every cup ever run, so it can vouch
    # for a cup the pipeline never processed (134, 138). Verified against the 138
    # screenshots: all ten of its recorded eliminations matched round for round.
    lexer_elims, lexer_rounds = xlsx_elim_rounds(num)
    if expected is None:
        expected = lexer_rounds
    # A cup whose own elimination records are known to be wrong can say so, with
    # its reasoning, rather than being unpublishable forever. COTD 134 is the
    # case: our block was written by a script that numbered the discovery round,
    # so it claims 16 where the truth is 15. The structural checks below still
    # apply, and the override reports itself on every build.
    override = doc.get('round_count_override') or {}
    override_note = ''
    if override.get('value'):
        override_note = (f"round count overridden to {override['value']} "
                         f"(records say {expected}): {override.get('why') or 'no reason given'}")
        expected = int(override['value'])
    declared = bool(doc.get('complete'))
    # The structural test, which needs no outside source and cannot be argued
    # with: a finished cup runs 1..N with no gaps and ends with two players
    # racing for it. A transcription in progress fails one or the other.
    numbers = sorted(r for r, _ in elim)
    contiguous = numbers == list(range(1, len(numbers) + 1))
    final_two = len(elim[-1][1]) == 2
    if not (contiguous and final_two):
        progress = f'{len(elim)} of {expected} rounds' if expected else f'{len(elim)} rounds'
        why = ('rounds are not 1..N without gaps' if not contiguous
               else f'the last round has {len(elim[-1][1])} racers, not the 2 of a final')
        return _stop(f'{progress} transcribed so far ({why}), held back until it is finished')
    # Structure alone cannot spot a file holding only the final round, so the
    # recorded round count still blocks when we have one.
    if expected is not None and len(elim) != expected:
        return _stop(f'{len(elim)} rounds transcribed but the elimination records say '
                     f'{expected}. Either it is unfinished, or those records are wrong '
                     f'for this cup and need fixing first')
    gripes_count = None
    if expected is None and not declared:
        return _stop(f'{len(elim)} rounds transcribed with nothing to check the count '
                     f'against; set "complete": true to publish')

    cup = {
        'cup': f'COTD {num}',
        'num': num,
        'map': cup_row.get('map') or '',
        'date': cup_row.get('date') or '',
        'field': cup_row.get('lobby_size') or len(cup_row['players']),
    }
    # Cross-check against Lexer's elimination order: somebody he records as
    # knocked out in round R cannot still be racing in a later round. Catches a
    # misread name or a round transcribed under the wrong number.
    ghosts_in_the_field = []
    for rnd_no, board in elim:
        for raw, _t in board:
            out_in = lexer_elims.get(normalize_name(raw))
            if out_in is not None and rnd_no > out_in:
                ghosts_in_the_field.append(f'{normalize_name(raw)} in R{rnd_no} (out in R{out_in})')

    cup.update(round_metrics(boards, winner))
    cup['src'] = 'partial'
    cup['source'] = doc.get('source') or 'reconstructed from screenshots'
    raced = Counter()
    for _, board in elim:
        for n, _t in board:
            raced[normalize_name(n)] += 1
    gripes = []
    if override_note:
        gripes.append(override_note)
    if gripes_count:
        gripes.append(gripes_count)
    if unknown_msg:
        gripes.append(unknown_msg)
    if ghosts_in_the_field:
        gripes.append("racing after Lexer's sheet has them eliminated: "
                      + ', '.join(ghosts_in_the_field))
    if gripes:
        return (cup, raced), f'partial_rounds/cotd_{num}.json: ' + '; '.join(gripes)
    return (cup, raced), None


# ------------------------------------------------------------------- the logs

def main():
    # Greek-mu player names crash a cp1252 console. Only as a script: an
    # importer owns its own stdout (elo_engine learned this the hard way).
    sys.stdout.reconfigure(encoding='utf-8')

    warnings = []
    cups_out, raced_total, led_total = [], Counter(), Counter()

    log_nums = sorted(
        int(re.fullmatch(r'cotd_(\d+)\.log', os.path.basename(p)).group(1))
        for p in glob.glob(os.path.join(LOG_DIR, 'cotd_*.log'))
        if re.fullmatch(r'cotd_\d+\.log', os.path.basename(p))
    )

    for num in log_nums:
        with open(os.path.join(LOG_DIR, f'cotd_{num}.log'), encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        result, warn = analyze(num, lines)
        if warn:
            warnings.append(warn)
            continue
        cup, raced = result
        cups_out.append(cup)
        raced_total.update(raced)
        for l in cup['leaders']:
            if l:
                led_total[l] += 1

    covered = {c['num'] for c in cups_out}

    # ---------------------------------------------------- partial (screenshots)

    for path in sorted(glob.glob(os.path.join(PARTIAL_DIR, 'cotd_*.json'))):
        result, warn = load_partial_cup(path)
        # A warning here can be fatal (no result) or advisory (names dropped but
        # the cup is still usable). Report either way, keep whatever parsed.
        if warn:
            warnings.append(warn)
        if result is None:
            continue
        cup, raced = result
        if cup['num'] in covered:
            warnings.append(f"{os.path.basename(path)}: COTD {cup['num']} already has a "
                            f"real log, the log is the authority, partial reconstruction skipped")
            continue
        cups_out.append(cup)
        raced_total.update(raced)
        for l in cup['leaders']:
            if l:
                led_total[l] += 1
        covered.add(cup['num'])

    cups_out.sort(key=lambda c: c['num'])

    # --------------------------------------------------------- historic (by hand)

    manual = []
    doc = {}
    if os.path.exists(MANUAL):
        with open(MANUAL, encoding='utf-8') as f:
            doc = json.load(f)
        for e in doc.get('sweeps', []):
            num = int(e['cup'])
            row = CUPS.get(f'COTD {num}')
            if not row or not row.get('players'):
                warnings.append(f"sweeps_manual: COTD {num} is not a cup in cups.json, dropped")
                continue
            real = normalize_name(next((p['name'] for p in row['players'] if p['pos'] == 1), ''))
            claimed = normalize_name(e['winner'])
            if claimed != real:
                warnings.append(
                    f"sweeps_manual: COTD {num} says {e['winner']!r} swept it but {real} won that cup, dropped")
                continue
            if num in covered:
                # A real log or a partial reconstruction is the authority for its
                # own cup; a sweeps_manual entry there is either redundant or
                # wrong, and either way it must be looked at.
                computed = next(c for c in cups_out if c['num'] == num)
                origin = 'log' if computed['src'] == 'log' else 'screenshot reconstruction'
                state = f'already counted from the {origin}' if computed['sweep'] else \
                        f"contradicted by the {origin} ({computed['winner']} led {computed['led']}/{computed['rounds']})"
                warnings.append(f"sweeps_manual: COTD {num} {state}, dropped")
                continue
            manual.append({
                'cup': f'COTD {num}', 'num': num, 'winner': real,
                'rounds': e.get('rounds') or elim_round_count(num, warnings), 'src': 'manual',
                'source': e.get('source') or 'manual review',
                'note': e.get('note') or '', 'warmup': False,
                'map': row.get('map') or '', 'date': row.get('date') or '',
                'field': row.get('lobby_size') or len(row['players']),
            })

    sweeps = [{
        'cup': c['cup'], 'num': c['num'], 'winner': c['winner'], 'rounds': c['rounds'],
        'src': c['src'], 'source': 'mod log' if c['src'] == 'log' else c['source'],
        'note': '', 'warmup': c['warmup'],
        'map': c['map'], 'date': c['date'], 'field': c['field'],
    } for c in cups_out if c['sweep']] + manual
    sweeps.sort(key=lambda s: s['num'])

    # --------------------------------------------------- all-time sweep counts

    # The logs can only ever name sweeps from COTD 136 on. Lexer's sheet counts
    # them over the whole history, so it owns the headline number and what we
    # can name from a log or a dated entry is the detail underneath it.
    named_count = Counter(s['winner'] for s in sweeps)
    known_players = {normalize_name(p['name']) for c in CUPS.values() for p in c['players']}

    tdoc = doc.get('totals') or {}
    totals = []
    for raw, n in (tdoc.get('counts') or {}).items():
        name = normalize_name(raw)
        if name not in known_players:
            warnings.append(f"sweeps_manual totals: {raw!r} has never raced a COTD, dropped")
            continue
        named = named_count.get(name, 0)
        if n < named:
            warnings.append(
                f"sweeps_manual totals: {name} is down as {n} all time but {named} "
                f"are already named from the logs, using {named}")
            n = named
        totals.append({'name': name, 'total': n, 'named': named})
    totals.sort(key=lambda t: (-t['total'], t['name'].lower()))
    # Anyone the logs caught but the sheet does not list yet.
    for name, named in named_count.items():
        if not any(t['name'] == name for t in totals):
            if tdoc.get('counts'):
                warnings.append(f"sweeps_manual totals: {name} has {named} named sweep(s) "
                                f"but no all-time count, listing the named ones")
            totals.append({'name': name, 'total': named, 'named': named})

    totals_meta = {
        'source': tdoc.get('source') or '',
        'note': tdoc.get('note') or '',
        'rows': totals,
        'total': sum(t['total'] for t in totals),
        'named': sum(t['named'] for t in totals),
    }

    # ------------------------------------------------------------ per-player rows

    sweep_count = Counter({t['name']: t['total'] for t in totals})
    win_count = Counter(c['winner'] for c in cups_out)
    # A near miss = led more rounds than anyone else in a cup and still lost it.
    near = Counter()
    for c in cups_out:
        others = Counter(l for l in c['leaders'] if l and l != c['winner'])
        if others:
            name, n = others.most_common(1)[0]
            if n > c['led']:
                near[name] += 1

    MIN_ROUNDS = 20  # roughly two cups' worth of rounds raced
    players = []
    # Anyone who swept a cup is listed even if the sweep predates the logs, so a
    # historic name never goes missing from the board that counts sweeps.
    for name in set(raced_total) | set(sweep_count):
        rounds = raced_total.get(name, 0)
        led = led_total.get(name, 0)
        if rounds < MIN_ROUNDS and not led and not sweep_count.get(name):
            continue
        players.append({
            'name': name, 'led': led, 'rounds': rounds,
            'share': round(100 * led / rounds, 1) if rounds else 0.0,
            'sweeps': sweep_count.get(name, 0), 'wins': win_count.get(name, 0),
            'near': near.get(name, 0),
        })
    players.sort(key=lambda p: (-p['led'], -p['share'], p['name'].lower()))

    gap = [n for n in range(min(covered), max(covered) + 1) if n not in covered] if covered else []
    partial_nums = sorted(c['num'] for c in cups_out if c['src'] == 'partial')
    # The whole series, which the all-time counts are measured against. Not the
    # same as the last cup WITH a log, which is all `coverage` knows about.
    mainline = [int(cid.split()[1]) for cid in CUPS if re.fullmatch(r'COTD \d+', cid)]
    output = {
        'generated_through': f'COTD {max(covered)}' if covered else None,
        'last_cup': max(mainline) if mainline else None,
        'coverage': {
            'first': min(covered) if covered else None,
            'last': max(covered) if covered else None,
            'cups': len(cups_out),
            'rounds': sum(c['rounds'] for c in cups_out),
            'missing': gap,
            'partial': partial_nums,
            'min_rounds': MIN_ROUNDS,
        },
        'totals': totals_meta,
        'sweeps': sweeps,
        'cups': cups_out,
        'players': players,
    }

    with open(_p('rounds.json'), 'w', encoding='utf-8') as f:
        json.dump(output, f, separators=(',', ':'), ensure_ascii=False)

    kb = os.path.getsize(_p('rounds.json')) / 1024
    print(f"rounds.json written ({kb:.0f} KB) — {len(cups_out)} cups with round data "
          f"(COTD {output['coverage']['first']}-{output['coverage']['last']}"
          + (f", no data for {gap}" if gap else "")
          + (f", {partial_nums} from screenshots not a log" if partial_nums else "")
          + f"), {output['coverage']['rounds']} rounds")

    src = f" ({totals_meta['source']})" if totals_meta['source'] else ''
    print(f"\n== Clean sweeps, all time: {totals_meta['total']}{src} ==")
    for t in totals:
        print(f"  {t['total']:>3}  {t['name']:<14} {t['named']} pinned to a cup")

    print(f"\n== Named sweeps: {len(sweeps)} ==")
    for s in sweeps:
        tag = 'log' if s['src'] == 'log' else s['source']
        extra = ' +warmup' if s['warmup'] else ''
        rounds = f"{s['rounds']}/{s['rounds']} rounds" if s['rounds'] else 'rounds unknown'
        print(f"  {s['cup']:<9} {s['winner']:<14} {rounds}{extra}  [{tag}]")

    nearly = sorted((c for c in cups_out if not c['sweep']),
                    key=lambda c: (len(c['dropped']),
                                   min([d['margin'] for d in c['dropped'] if d['margin'] is not None] or [9e9])))
    print("\n== Nearly swept it ==")
    for c in nearly[:5]:
        d = c['dropped']
        tight = min((x for x in d if x['margin'] is not None),
                    key=lambda x: x['margin'], default=None)
        detail = f" tightest R{tight['round']} to {tight['to']} by {tight['margin']:.3f}s" if tight else ''
        print(f"  {c['cup']:<9} {c['winner']:<14} {c['led']}/{c['rounds']}, dropped {len(d)}.{detail}")

    print("\n== Rounds led ==")
    for p in players[:10]:
        print(f"  {p['led']:>4}/{p['rounds']:<4} ({p['share']:>4.1f}%)  {p['name']:<14} "
              f"wins {p['wins']}  sweeps {p['sweeps']}  near {p['near']}")

    if warnings:
        print(f"\n== {len(warnings)} warnings ==")
        for w in warnings:
            print(f"  ! {w}")


if __name__ == '__main__':
    main()
