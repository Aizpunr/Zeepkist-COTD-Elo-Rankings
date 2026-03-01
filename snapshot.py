"""
snapshot.py — write snapshot.json from data.json

Usage:
  python snapshot.py          → snapshot = current standings (no arrows until new cup)
  python snapshot.py 130      → snapshot = standings as of cup 130
"""
import json, os, sys

base = os.path.dirname(os.path.abspath(__file__))
def _p(f): return os.path.join(base, f)

DECAY = 0.995
GRACE = 3

with open(_p('data.json')) as f:
    data = json.load(f)

std_players  = data['standard']['l']
w_players    = data['weighted']['l']
std_pure     = data.get('standard_pure', {}).get('l', [])
w_pure       = data.get('weighted_pure', {}).get('l', [])
season       = data.get('season_2026', {}).get('l', [])

# Find highest cup number across all history entries
def max_cup(players):
    if not players: return 0
    return max(h['c'] for p in players for h in p['history'])

current_cup = max(max_cup(std_players), max_cup(w_players))

target_cup = int(sys.argv[1]) if len(sys.argv) > 1 else current_cup
print(f"Current cup: {current_cup}  |  Snapshot at cup: {target_cup}")

def build_snap_at(players, target, no_decay=False):
    entries = []
    for p in players:
        hist_before = [h for h in p['history'] if h['c'] <= target]
        if not hist_before:
            continue
        last = max(hist_before, key=lambda h: h['c'])
        raw = last['r']
        missed = target - last['c']
        if no_decay:
            active = round(raw, 1)
        else:
            active = round(1500 + (raw - 1500) * (DECAY ** (missed - GRACE)), 1) if missed > GRACE else round(raw, 1)
        wins = sum(1 for h in hist_before if h['p'] == 1)
        pods = sum(1 for h in hist_before if h['p'] <= 3)
        entries.append((p['name'], raw, active, wins, pods))
    entries.sort(key=lambda x: x[2], reverse=True)  # rank by active
    return {name: [i + 1, raw, wins, pods] for i, (name, raw, _, wins, pods) in enumerate(entries[:150])}

with open(_p('lexercurse.json')) as f:
    curse_players = json.load(f).get('l', [])

snap = {
    'std':      build_snap_at(std_players, target_cup),
    'w':        build_snap_at(w_players,   target_cup),
    'std_pure': build_snap_at(std_pure,    target_cup),
    'w_pure':   build_snap_at(w_pure,      target_cup),
    'curse':    build_snap_at(curse_players, target_cup),
    'season':   build_snap_at(season,      target_cup, no_decay=True),
}

with open(_p('snapshot.json'), 'w') as f:
    json.dump(snap, f, separators=(',', ':'))
print(f"snapshot.json written (cup {target_cup})")
