"""
build_consistency.py — compute position consistency stats for all players.
Spread = standard deviation of finishing positions.
"""
import json, os, sys, statistics
sys.stdout.reconfigure(encoding='utf-8')

base = os.path.dirname(os.path.abspath(__file__))
def _p(f): return os.path.join(base, f)

with open(_p('alldata.json'), encoding='utf-8') as f:
    data = json.load(f)

max_cups = max(p['c'] for p in data['weighted'])
MIN_CUPS = max(1, round(max_cups * 0.1))
print(f"Appearance leader: {max_cups} cups → min threshold: {MIN_CUPS}")

players = []
for p in data['weighted']:
    if p['c'] < MIN_CUPS:
        continue
    positions = [h['p'] for h in p['h']]
    history = [{'c': h['c'], 'p': h['p']} for h in p['h']]
    spread = round(statistics.stdev(positions), 2)
    avg = round(statistics.mean(positions), 1)
    best = p['b']
    worst = max(positions)
    pb_gap = round(avg - best, 1)

    players.append({
        'name': p['n'],
        'cups': p['c'],
        'best': best,
        'avg': avg,
        'spread': spread,
        'pb_gap': pb_gap,
        'worst': worst,
        'positions': positions,
        'history': history
    })

# Sort by spread ascending (most consistent first)
players.sort(key=lambda x: x['spread'])

output = {'players': players}

out_path = _p('consistency.json')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(output, f, separators=(',', ':'), ensure_ascii=False)

print(f"Generated consistency data for {len(players)} players (min {MIN_CUPS} cups)")
print(f"Written to {os.path.basename(out_path)}")

print("\nMost Consistent (lowest spread):")
for p in players[:5]:
    print(f"  {p['name']}: spread={p['spread']}, avg={p['avg']}, best={p['best']}, cups={p['cups']}")

print("\nBiggest Wildcards (highest spread):")
for p in sorted(players, key=lambda x: -x['spread'])[:5]:
    print(f"  {p['name']}: spread={p['spread']}, avg={p['avg']}, best={p['best']}, cups={p['cups']}")

print("\nClosest to PB:")
for p in sorted(players, key=lambda x: x['pb_gap'])[:5]:
    print(f"  {p['name']}: pb_gap={p['pb_gap']}, avg={p['avg']}, best={p['best']}, cups={p['cups']}")
