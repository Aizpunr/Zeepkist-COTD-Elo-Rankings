"""
build_stability_history.py — the stability point of every regular, cup by cup.

elo_stability.py answers "what rating is each player playing like right now".
This asks the same question as of every past cup: the ratings and results as
they stood after cup N, over the 12-cup window ending at N. Same maths, so the
newest snapshot equals elo_stability.json (tests/test_stability_history.py).

Only players with MIN_CUPS of the window's 12 cups get a point: three cups is
enough for "who is cooking this month" but too few to say someone played like a
2100 for a stretch.

Each snapshot also stores the average of the ten highest ratings among the
players active in its window. The page uses it to bring old cups to today's
scale: everyone started at 1500 in 2023, so the same dominance reads lower then.

Output: stability_history.json, consumed by the History tab of stability.html.
A snapshot is recomputed only when its inputs changed (new cup, alias merge,
corrected result), so a normal cup costs one snapshot.
"""
import hashlib, json, os, sys
sys.stdout.reconfigure(encoding='utf-8')

base = os.path.dirname(os.path.abspath(__file__))
def _p(f): return os.path.join(base, f)

# ── Parameters (the first six mirror elo_stability.py) ──────
LAST_N     = 12
K_BASE     = 32
SEARCH_LO  = 1300
SEARCH_HI  = 4000
SEARCH_TOL = 0.01
MIN_CUPS   = 6        # elo_stability.py asks for 3; see the docstring
VERSION    = 1        # bump to force every snapshot to be recomputed
OUT        = _p('stability_history.json')


def pct_mult(pos, n):
    pct = pos / n
    if pct <= 0.08: return 3.0
    if pct <= 0.15: return 2.0
    if pct <= 0.25: return 1.3
    if pct <= 0.50: return 0.8
    return 0.5


def window_stats(players, cup):
    """Per-player inputs as they stood after `cup`, for everyone in the window."""
    start = cup - LAST_N + 1
    stats = {}
    for p in players:
        hist = [h for h in p['h'] if h['c'] <= cup]
        recent = [h for h in hist if h['c'] >= start]
        if not recent:
            continue
        stats[p['n']] = {
            'attendance': len(recent) / LAST_N,
            'norm_pos': [min(max((h['p'] - 1) / 51, 0.0), 1.0) for h in recent],
            'rating': hist[-1]['r'],
            'recent': len(recent),
        }
    return stats


def fingerprint(stats):
    blob = json.dumps([VERSION, MIN_CUPS, sorted(
        (n, s['rating'], s['recent'], s['norm_pos']) for n, s in stats.items())],
        ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha1(blob.encode('utf-8')).hexdigest()[:12]


def snapshot(stats):
    """({name: stability point}, top-10 average rating) for one window."""
    names = sorted(stats, key=lambda n: stats[n]['rating'], reverse=True)
    n_expected = 1 + sum(stats[n]['attendance'] for n in names)
    n_field = max(2, round(n_expected))
    k_unit = K_BASE / max(1, n_field - 1)

    # (rating, attendance, expected position) per player, strongest first
    field, cumulative = [], 0.0
    for n in names:
        s = stats[n]
        field.append((s['rating'], s['attendance'], max(1, round(1 + cumulative))))
        cumulative += s['attendance']
    total_ra = sum(r * a for r, a, _ in field)
    top10 = sum(r for r, _, _ in field[:10]) / min(10, len(field))

    points = {}
    for i, name in enumerate(names):
        s = stats[name]
        if s['recent'] < MIN_CUPS:
            continue
        opp_sum = total_ra - field[i][0] * field[i][1]
        positions = [max(1, round(q * (n_field - 1) + 1)) for q in s['norm_pos']]
        # Only the expected score depends on the rating being tested, so the
        # sums over this player's finishing positions are taken once per rival:
        # won = sum of att * multiplier * result, played = sum of att * multiplier.
        rivals = []
        for j, (r, a, pos) in enumerate(field):
            if j == i:
                continue
            won = played = 0.0
            for pp in positions:
                m = a * pct_mult(min(pp, pos), n_field)
                played += m
                won += m * (1.0 if pp < pos else (0.0 if pp > pos else 0.5))
            rivals.append((r, won, played))

        def delta(test):
            avg_field = (test * s['attendance'] + opp_sum) / max(1, n_expected)
            total = 0.0
            for r, won, played in rivals:
                ev = 1.0 / (1.0 + 10.0 ** ((r - test) / 400.0))
                pair_q = (test + r) / (2 * avg_field) if avg_field > 0 else 1.0
                total += pair_q * (won - played * ev)
            return k_unit * total / len(positions)

        if delta(SEARCH_LO) <= 0:
            point = SEARCH_LO
        elif delta(SEARCH_HI) >= 0:
            point = SEARCH_HI
        else:
            lo, hi = SEARCH_LO, SEARCH_HI
            point = None
            for _ in range(60):
                mid = (lo + hi) / 2
                d = delta(mid)
                if abs(d) < SEARCH_TOL:
                    point = mid
                    break
                if d > 0:
                    lo = mid
                else:
                    hi = mid
            if point is None:
                point = (lo + hi) / 2
        points[name] = round(point, 1)
    return points, round(top10, 1)


def main():
    with open(_p('alldata.json'), encoding='utf-8') as f:
        players = json.load(f)['weighted']
    # Troll and Roulette cups carry fractional numbers (15.5): they count
    # inside a window, as in elo_stability.py, but get no snapshot of their own.
    cups = sorted({h['c'] for p in players for h in p['h'] if isinstance(h['c'], int)})
    cups = [c for c in cups if c >= LAST_N]

    old = {}
    if os.path.exists(OUT):
        try:
            with open(OUT, encoding='utf-8') as f:
                old = json.load(f).get('cups', {})
        except (OSError, ValueError):
            old = {}

    out, computed = {}, 0
    for cup in cups:
        stats = window_stats(players, cup)
        fp = fingerprint(stats)
        prev = old.get(str(cup))
        if prev and prev.get('h') == fp:
            out[str(cup)] = prev
            continue
        points, top10 = snapshot(stats)
        out[str(cup)] = {'t': top10, 'h': fp, 'p': points}
        computed += 1

    doc = {'through': cups[-1], 'window': LAST_N, 'min_cups': MIN_CUPS, 'cups': out}
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, separators=(',', ':'), ensure_ascii=False)
    print(f"stability_history.json written (COTD {cups[0]} to {cups[-1]}, "
          f"{computed} of {len(cups)} snapshots recomputed)")


if __name__ == '__main__':
    main()
