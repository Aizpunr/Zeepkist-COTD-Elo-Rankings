"""
build_giantkillers.py — compute biggest upsets from COTD cup history.
Pre-cup ELO derived by walking cups.json in order.
Upset = winner was not the highest-rated player entering the cup.
"""
import json, os, sys
sys.stdout.reconfigure(encoding='utf-8')

base = os.path.dirname(os.path.abspath(__file__))
def _p(f): return os.path.join(base, f)

with open(_p('cups.json'), encoding='utf-8') as f:
    cups = json.load(f)

print(f"Loaded {len(cups)} cups")

# Walk cups in order, tracking running ELO
running = {}  # player name -> latest rating_after
upsets = []

for cup in cups:
    players = cup.get('players', [])
    if not players:
        continue

    cup_id = cup['id']
    lobby_size = cup.get('lobby_size', len(players))
    strength = cup.get('strength', 0)
    is_troll = 'Troll' in cup_id or 'Roulette' in cup_id

    # Compute pre-cup ELO for each player
    lobby = []
    for p in players:
        name = p['name']
        pre_elo = running.get(name, 1500)
        lobby.append({
            'name': name,
            'pos': p['pos'],
            'pre_elo': pre_elo,
            'post_elo': p['rating_after']
        })

    # Sort by pre-ELO descending to find rankings
    lobby_sorted = sorted(lobby, key=lambda x: -x['pre_elo'])

    # Find winner (lowest position number)
    winner = min(lobby, key=lambda x: x['pos'])

    # Find winner's ELO rank (1-indexed, handle ties conservatively: best rank among tied)
    winner_pre = winner['pre_elo']
    elo_rank = sum(1 for p in lobby if p['pre_elo'] > winner_pre) + 1

    # Top ELO player
    top = lobby_sorted[0]

    # Deficit
    deficit = round(top['pre_elo'] - winner_pre, 1)

    # Beaten above = players with higher pre-ELO than winner
    beaten_above = elo_rank - 1

    # ELO gain
    elo_gain = round(winner['post_elo'] - winner_pre, 1)

    # Extract cup number
    cup_num = cup_id.replace('COTD ', '').replace('Troll COTD ', '').replace('Roulette COTD ', '')
    try:
        cup_num = float(cup_num)
    except ValueError:
        cup_num = 0

    # Record upset if winner wasn't the favorite
    if elo_rank > 1 and deficit > 0:
        upsets.append({
            'cup_id': cup_id,
            'cup_num': cup_num,
            'winner': winner['name'],
            'winner_pre_elo': round(winner_pre, 1),
            'elo_rank': elo_rank,
            'lobby_size': lobby_size,
            'top_elo_player': top['name'],
            'top_elo_value': round(top['pre_elo'], 1),
            'deficit': deficit,
            'beaten_above': beaten_above,
            'elo_gain': elo_gain,
            'strength': strength,
            'is_troll': is_troll
        })

    # Update running ELOs
    for p in lobby:
        running[p['name']] = p['post_elo']

# Sort by deficit descending
upsets.sort(key=lambda x: -x['deficit'])

# Repeat killers (2+ upsets)
from collections import Counter, defaultdict
winner_counts = Counter(u['winner'] for u in upsets)
repeat_data = defaultdict(lambda: {'cups': [], 'deficits': []})
for u in upsets:
    if winner_counts[u['winner']] >= 2:
        repeat_data[u['winner']]['cups'].append(u['cup_id'])
        repeat_data[u['winner']]['deficits'].append(u['deficit'])

repeat_killers = sorted([
    {
        'name': name,
        'count': len(d['cups']),
        'cups': d['cups'],
        'avg_deficit': round(sum(d['deficits']) / len(d['deficits']), 1)
    }
    for name, d in repeat_data.items()
], key=lambda x: -x['avg_deficit'])

# Output
output = {
    'upsets': upsets,
    'repeat_killers': repeat_killers
}

out_path = _p('giantkillers.json')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(output, f, separators=(',', ':'), ensure_ascii=False)

print(f"\nGenerated {len(upsets)} upsets, {len(repeat_killers)} repeat killers")
print(f"Written to {os.path.basename(out_path)}")

# Top 5 upsets
print("\nTop 5 biggest upsets:")
for i, u in enumerate(upsets[:5]):
    print(f"  {i+1}. {u['cup_id']}: {u['winner']} (ELO {u['winner_pre_elo']}, "
          f"ranked {u['elo_rank']}/{u['lobby_size']}) beat {u['top_elo_player']} "
          f"({u['top_elo_value']}) — deficit {u['deficit']}")

# Repeat killers
if repeat_killers:
    print(f"\nRepeat Giant Killers:")
    for rk in repeat_killers[:5]:
        print(f"  {rk['name']}: {rk['count']} upsets, avg deficit {rk['avg_deficit']}")
