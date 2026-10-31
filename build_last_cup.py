"""
build_last_cup.py — what happened at the newest COTD, for last_cup.html.

Reads cups.json, fastest.json and streaks.json (so it runs after
build_fastest.py and build_streaks.py). Regular COTD cups only, the same
series build_streaks.py uses. Output: last_cup.json.

  winner        who won, and how many COTD wins that makes
  fastest       the cup's fastest time, from fastest.json
  pbs           players who finished higher than ever before (debuts excluded)
  broken        streaks that were alive going in and ended at this cup,
                including the Big 3's run of consecutive wins
  active        streaks this cup extended, per cutline
"""
import json, os, re, sys
sys.stdout.reconfigure(encoding='utf-8')

base = os.path.dirname(os.path.abspath(__file__))
def _p(f): return os.path.join(base, f)

def load(f):
    with open(_p(f), encoding='utf-8') as fh:
        return json.load(fh)

BIG3 = ['Kernkob', 'justMaki', 'ZOMAN']  # same set as build_big3.py

cups = load('cups.json')
reg = [c for c in cups if re.fullmatch(r'COTD \d+', c['id']) and c['players']]
reg.sort(key=lambda c: int(c['id'].split()[1]))
last, prev = reg[-1], reg[:-1]
pos_now = {p['name']: p['pos'] for p in last['players']}

# ── winner ──
winner = last['players'][0]['name']
wins = sum(1 for c in reg if c['players'][0]['name'] == winner)
podium = [{'name': p['name'], 'pos': p['pos']} for p in last['players'] if p['pos'] <= 3]

# ── fastest ──
fastest = next((f for f in load('fastest.json') if f['cup'] == last['id']), None)

# ── cup PBs: a better finish than any earlier regular COTD ──
best_before, cups_before = {}, {}
for c in prev:
    for p in c['players']:
        n = p['name']
        cups_before[n] = cups_before.get(n, 0) + 1
        if n not in best_before or p['pos'] < best_before[n]:
            best_before[n] = p['pos']
pbs = [{'name': n, 'pos': pos, 'prev_best': best_before[n], 'cups': cups_before[n] + 1}
       for n, pos in pos_now.items() if n in best_before and pos < best_before[n]]
pbs.sort(key=lambda r: (r['pos'], r['name'].lower()))

# ── streaks broken and extended ──
def last_attended_before(name):
    for c in reversed(prev):
        if any(p['name'] == name for p in c['players']):
            return c['id']
    return None

broken, active = [], []
for card in load('streaks.json')['cards']:
    record = max((s['len'] for s in card['streaks']), default=0)
    lens = sorted((s['len'] for s in card['streaks']), reverse=True)
    for s in card['streaks']:
        n = s['name']
        if n not in pos_now:
            continue
        row = {'card': card['label'], 'cut': card['cut'], 'name': n, 'len': s['len'],
               'span': s['span'], 'alltime_rank': lens.index(s['len']) + 1,
               'record': s['len'] == record}
        if s['active']:
            active.append(row)
        elif pos_now[n] > card['cut'] and s['span'][1] == last_attended_before(n):
            row['pos'] = pos_now[n]
            broken.append(row)

# The Big 3's run of consecutive wins, counted over the whole series.
runs, run = [], 0
for c in reg:
    run = run + 1 if c['players'][0]['name'] in BIG3 else 0
    runs.append(run)
big3_going_in = runs[-2] if len(runs) > 1 else 0
if winner not in BIG3 and big3_going_in >= 3:
    broken.append({'card': 'Big 3 wins', 'cut': 1, 'name': 'Big 3', 'len': big3_going_in,
                   'span': [reg[-1 - big3_going_in]['id'], prev[-1]['id']],
                   'record': big3_going_in == max(runs),
                   'record_len': max(runs), 'pos': None})
broken.sort(key=lambda r: (-r['len'], r['name'].lower()))
active.sort(key=lambda r: (-r['len'], r['name'].lower()))

out = {
    'cup': last['id'], 'map': last.get('map'), 'mapper': last.get('mapper'),
    'date': last.get('date'), 'field': len(last['players']),
    'winner': {'name': winner, 'wins': wins}, 'podium': podium,
    'fastest': fastest, 'pbs': pbs, 'broken': broken, 'active': active,
}
with open(_p('last_cup.json'), 'w', encoding='utf-8') as f:
    json.dump(out, f, separators=(',', ':'), ensure_ascii=False)

print(f"last_cup.json written ({last['id']})")
print(f"  winner {winner} (win #{wins}); fastest "
      f"{fastest['time'] if fastest else '-'} {fastest['player'] if fastest else ''}")
print(f"  {len(pbs)} cup PBs, {len(broken)} streaks broken, {len(active)} active streaks extended")
for b in broken:
    print(f"  broken: {b['name']} {b['card']} {b['len']}{' (record)' if b['record'] else ''}")
