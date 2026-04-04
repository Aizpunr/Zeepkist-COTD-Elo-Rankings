"""Build big3_data.json from cups.json — Big 3 H2H and per-cup presence data."""
import json, os

_dir = os.path.dirname(os.path.abspath(__file__))
_p = lambda f: os.path.join(_dir, f)

BIG3 = ['Kernkob', 'justMaki', 'ZOMAN']

cups = json.load(open(_p('cups.json'), encoding='utf-8'))

cup_data = []
h2h = {}
for pair in [('Kernkob', 'justMaki'), ('Kernkob', 'ZOMAN'), ('justMaki', 'ZOMAN')]:
    h2h[f'{pair[0]}_vs_{pair[1]}'] = [0, 0]

for cup in cups:
    players = {p['name']: p['pos'] for p in cup['players']}
    winner = cup['players'][0]['name'] if cup['players'] else None

    big3_present = {}
    for name in BIG3:
        if name in players:
            big3_present[name] = players[name]

    cup_data.append({
        'c': cup['id'],
        'winner': winner,
        'big3': big3_present,
    })

    # H2H: count cups where both played and one beat the other
    for a, b in [('Kernkob', 'justMaki'), ('Kernkob', 'ZOMAN'), ('justMaki', 'ZOMAN')]:
        if a in players and b in players:
            key = f'{a}_vs_{b}'
            if players[a] < players[b]:
                h2h[key][0] += 1
            elif players[b] < players[a]:
                h2h[key][1] += 1

output = {'cups': cup_data, 'h2h': h2h}
with open(_p('big3_data.json'), 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, separators=(',', ':'))

print(f"big3_data.json written ({len(cup_data)} cups)")
for k, v in h2h.items():
    print(f"  {k}: {v[0]}-{v[1]}")
