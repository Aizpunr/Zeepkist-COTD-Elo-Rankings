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
from elo_engine import CANONICAL

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
        finishers = sorted((t, n) for n, t in board if t is not None)
        order = [normalize_name(n) for _, n in finishers]
        lead = order[0] if order else None
        leaders.append(lead)
        # A player who DNF'd or was not on the board has no meaningful rank.
        ranks.append(order.index(winner) + 1 if winner in order else None)
        if lead and lead != winner:
            # The rounds standing between this cup and a clean sweep, and how
            # much the eventual winner lost each one by. The margin needs the
            # winner's own time for that round, which a screenshot may not show.
            wt = next((t for t, n in finishers if normalize_name(n) == winner), None)
            dropped.append({
                'round': rnd_no,
                'to': lead,
                'margin': round(wt - finishers[0][0], 5) if wt is not None else None,
            })

    seq = [l for l in leaders if l]
    warmup = next((b for r, b in boards if r == 0), [])
    warm_fin = sorted((t, n) for n, t in warmup if t is not None)
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
        'warmup': bool(warm_fin) and normalize_name(warm_fin[0][1]) == winner,
    }


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
    path = _p(f'cup_{num}.json')
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
    """A hand-reconstructed cup from partial_rounds/ (see its README). Reuses
    round_metrics() by treating each round's `visible` list as that round's
    board, same as a log's leaderboard block minus the players off screen."""
    with open(path, encoding='utf-8') as f:
        doc = json.load(f)
    num = doc['cup']
    _, winner, row = cup_context(num)
    if winner is None:
        return None, f'partial_rounds/cotd_{num}.json: COTD {num} not in cups.json, skipped'

    boards = []
    for r in doc['rounds']:
        board = []
        for e in r.get('visible', []):
            if not e.get('name'):
                continue  # illegible in the screenshot, not a real entry
            t = e.get('time')
            board.append((e['name'], None if t in (None, 'DNF') else float(t)))
        boards.append((r['round'], board))

    elim = [(r, b) for r, b in boards if r > 0]
    if not elim:
        return None, f'partial_rounds/cotd_{num}.json: no rounds, skipped'

    cup = {
        'cup': f'COTD {num}',
        'num': num,
        'map': row.get('map') or '',
        'date': row.get('date') or '',
        'field': row.get('lobby_size') or len(row['players']),
    }
    cup.update(round_metrics(boards, winner))
    cup['src'] = 'partial'
    cup['source'] = doc.get('source') or 'reconstructed from screenshots'
    raced = Counter()
    for _, board in elim:
        for n, _t in board:
            raced[normalize_name(n)] += 1
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
        if warn:
            warnings.append(warn)
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
                'rounds': e.get('rounds'), 'src': 'manual',
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
