"""
elo_stability.py — find the theoretical ELO stabilization point for each player.

For each player, computes the ELO at which their expected per-cup delta is zero,
given their attendance probability and historical finishing position distribution.

Complements elo_sim.py (Monte Carlo trajectory) with a deterministic analytical answer.
"""

import json, os, sys
sys.stdout.reconfigure(encoding='utf-8')

base = os.path.dirname(os.path.abspath(__file__))
def _p(f): return os.path.join(base, f)

# ── Parameters ──────────────────────────────────────────────
LAST_N     = 12       # cups to base patterns on (~3 months)
MIN_CUPS   = 3        # minimum recent cups to qualify
K_BASE     = 32
STARTING   = 1500
SEARCH_LO  = 1300
SEARCH_HI  = 4000
SEARCH_TOL = 0.01     # binary search convergence

def E(ra, rb):
    return 1.0 / (1.0 + 10.0 ** ((rb - ra) / 400.0))

def pct_mult(pos, n):
    pct = pos / n
    if pct <= 0.08: return 3.0
    if pct <= 0.15: return 2.0
    if pct <= 0.25: return 1.3
    if pct <= 0.50: return 0.8
    return 0.5

# ── Load data ───────────────────────────────────────────────
with open(_p('alldata.json'), encoding='utf-8') as f:
    data = json.load(f)

w_players = data['weighted']
current_cup = max(h['c'] for p in w_players for h in p['h'])
window_start = current_cup - LAST_N + 1

print(f"Current cup: {current_cup}  |  Window: cups {window_start}-{current_cup}")

# ── Build per-player stats ──────────────────────────────────
stats = {}
for p in w_players:
    name = p['n']
    recent = [h for h in p['h'] if h['c'] >= window_start]
    if not recent:
        continue
    attendance = len(recent) / LAST_N
    norm_positions = [
        min(max((h['p'] - 1) / 51, 0.0), 1.0)  # normalise to ~52-player field
        for h in recent
    ]
    stats[name] = {
        'attendance': attendance,
        'norm_pos': norm_positions,
        'rating': p['r'],
        'cups': p['c'],
        'recent': len(recent),
    }

print(f"Players in window: {len(stats)}  |  Qualifying ({MIN_CUPS}+ cups): "
      f"{sum(1 for s in stats.values() if s['recent'] >= MIN_CUPS)}")

# ── Build expected opponent pool ────────────────────────────
# Sort all players by rating for position assignment
all_names = sorted(stats.keys(), key=lambda n: stats[n]['rating'], reverse=True)
n_expected = 1 + sum(stats[n]['attendance'] for n in all_names)
n_field = max(2, round(n_expected))

# Pre-compute opponent data: (name, rating, attendance, expected_position)
# Expected position = 1 + sum(attendance of higher-rated players)
opponents_data = []
cumulative = 0.0
for name in all_names:
    s = stats[name]
    exp_pos = 1 + cumulative
    opponents_data.append((name, s['rating'], s['attendance'], exp_pos))
    cumulative += s['attendance']

avg_field_ratings = sum(s['rating'] * s['attendance'] for s in stats.values()) / max(1, sum(s['attendance'] for s in stats.values()))

# ── Expected delta computation ──────────────────────────────
def expected_delta(player_name, test_elo):
    """Compute expected ELO delta per cup for player at test_elo."""
    ps = stats[player_name]
    total_delta = 0.0

    for norm_p in ps['norm_pos']:
        # Map normalised position to absolute position in expected field
        pos_p = max(1, round(norm_p * (n_field - 1) + 1))
        cup_delta = 0.0

        # Recompute avg field with test_elo substituted
        opp_rating_sum = sum(r * a for n, r, a, _ in opponents_data if n != player_name)
        avg_field = (test_elo * ps['attendance'] + opp_rating_sum) / max(1, n_expected)

        for opp_name, opp_rating, opp_att, opp_exp_pos in opponents_data:
            if opp_name == player_name:
                continue

            # Adjust opponent position if player is ranked above them
            opp_pos = max(1, round(opp_exp_pos))

            ev = E(test_elo, opp_rating)
            s = 1.0 if pos_p < opp_pos else (0.0 if pos_p > opp_pos else 0.5)

            win_pos = min(pos_p, opp_pos)
            pair_q = (test_elo + opp_rating) / (2 * avg_field) if avg_field > 0 else 1.0
            k = K_BASE / max(1, n_field - 1) * pct_mult(win_pos, n_field) * pair_q

            cup_delta += opp_att * k * (s - ev)

        total_delta += cup_delta

    # Average over all historical positions
    return total_delta / len(ps['norm_pos'])


# ── Binary search for stability point ──────────────────────
def find_stability(player_name):
    lo, hi = SEARCH_LO, SEARCH_HI

    # Check if delta is positive at both ends (always gaining) or negative (always losing)
    d_lo = expected_delta(player_name, lo)
    d_hi = expected_delta(player_name, hi)

    if d_lo <= 0:
        return lo  # Even at minimum, player loses ELO
    if d_hi >= 0:
        return hi  # Even at maximum, player gains ELO

    for _ in range(60):
        mid = (lo + hi) / 2
        d = expected_delta(player_name, mid)
        if abs(d) < SEARCH_TOL:
            return mid
        if d > 0:
            lo = mid
        else:
            hi = mid

    return (lo + hi) / 2


# ── Main computation ────────────────────────────────────────
results = []
qualifying = [n for n in all_names if stats[n]['recent'] >= MIN_CUPS]

print(f"\nComputing stability points for {len(qualifying)} players...")

for i, name in enumerate(qualifying):
    s = stats[name]
    stability = find_stability(name)
    gap = s['rating'] - stability
    avg_pos = sum(h_p * 52 + 1 for h_p in s['norm_pos']) / len(s['norm_pos'])

    results.append({
        'name': name,
        'current_elo': round(s['rating'], 1),
        'stability_point': round(stability, 1),
        'gap': round(gap, 1),
        'attendance_pct': round(s['attendance'] * 100, 1),
        'cups_played': s['cups'],
        'recent_cups': s['recent'],
        'avg_position': round(avg_pos, 1),
        'status': 'Washed' if gap > s['rating'] * 0.02 else ('Cooking' if gap < -s['rating'] * 0.02 else 'Following Script'),
    })

    if (i + 1) % 20 == 0:
        print(f"  ...{i + 1}/{len(qualifying)}")

# Sort by stability point descending
results.sort(key=lambda x: x['stability_point'], reverse=True)

# ── Print results ───────────────────────────────────────────
print(f'\n{"#":<4} {"Name":<22} {"Current":>8} {"Stable":>8} {"Gap":>7}  {"Part%":>6}  {"Status"}')
print('-' * 70)
for i, r in enumerate(results[:30]):
    print(f'{i+1:<4} {r["name"]:<22} {r["current_elo"]:>8} {r["stability_point"]:>8} '
          f'{r["gap"]:>+7.1f}  {r["attendance_pct"]:>5}%  {r["status"]}')

# ── Write JSON ──────────────────────────────────────────────
output = {
    'parameters': {
        'last_n_cups': LAST_N,
        'current_cup': current_cup,
        'window_start': window_start,
        'min_cups': MIN_CUPS,
        'expected_field_size': round(n_expected, 1),
        'method': 'analytical_expected_value',
        'provisional_excluded': True,
    },
    'results': results,
}

with open(_p('elo_stability.json'), 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f'\nelo_stability.json written ({len(results)} players)')
