"""
build_streaks.py — consecutive-finish streak records for the Streaks cool-stat.

A streak = consecutive COTD cups a player ATTENDED finishing at or above a
cutline (pos <= cut). Absences are skipped (they do NOT break it); a finish past
the cutline breaks it; boundary ties count. Regular COTD cups only
(Troll/Roulette excluded). Output: streaks.json, consumed by streaks.html.
"""
import json, os, re, sys
sys.stdout.reconfigure(encoding='utf-8')

base = os.path.dirname(os.path.abspath(__file__))
def _p(f): return os.path.join(base, f)

with open(_p('cups.json'), encoding='utf-8') as f:
    cups = json.load(f)

# Regular COTD cups only, in chronological (numeric) order. (Cups 59-65 were
# briefly branded "COTW"; they've been renamed to COTD at the source, so a plain
# COTD match now covers the whole mainline series.)
reg = [c for c in cups if re.fullmatch(r'COTD \d+', c['id']) and c['players']]
reg.sort(key=lambda c: int(c['id'].split()[1]))

def pos_of(cup, name):
    for p in cup['players']:
        if p['name'] == name:
            return p.get('pos')
    return None  # absent from this cup

def all_streaks(name, cut):
    """Every maximal run of consecutive top-cut finishes for one player.

    Returns a list of {len, span, active}. A run ends either by a finish past
    the cutline (dead) or by reaching the latest cup still going (active). A
    player can legitimately own several long runs, so we keep them all and let
    the frontend choose between the true board and a one-per-player view.
    """
    streaks = []
    cur = 0
    start = last = None
    for c in reg:
        p = pos_of(c, name)
        if p is None:
            continue  # absence: skip, don't break
        if p <= cut:
            if cur == 0:
                start = c['id']
            cur += 1
            last = c['id']
        else:
            if cur > 0:
                streaks.append({'len': cur, 'span': [start, last], 'active': False})
            cur = 0
    if cur > 0:  # run still open at the latest cup = active
        streaks.append({'len': cur, 'span': [start, last], 'active': True})
    return streaks

# (key, label, cut, min_best to list)
CUTLINES = [
    ('wins',   'Wins',         1, 2),
    ('podium', 'Podium',       3, 3),
    ('single', 'Single Elim',  6, 3),
    ('double', 'Double Elim', 12, 3),
]

allnames = {p['name'] for c in reg for p in c['players']}

cards = []
for key, label, cut, min_len in CUTLINES:
    streaks = []
    for n in allnames:
        for s in all_streaks(n, cut):
            if s['len'] < min_len:
                continue
            streaks.append({'name': n, 'len': s['len'],
                            'active': s['active'], 'span': s['span']})
    # Longest first; active breaks ties (a live run edges a dead one of equal
    # length); then alphabetical. The frontend dedupes to one-per-player on toggle.
    streaks.sort(key=lambda s: (-s['len'], not s['active'], s['name'].lower()))
    cards.append({'key': key, 'label': label, 'cut': cut, 'streaks': streaks})

through = reg[-1]['id'] if reg else None
output = {'generated_through': through, 'cards': cards}

with open(_p('streaks.json'), 'w', encoding='utf-8') as f:
    json.dump(output, f, separators=(',', ':'), ensure_ascii=False)

print(f"streaks.json written (through {through})")
for card in cards:
    n_players = len({s['name'] for s in card['streaks']})
    print(f"\n== {card['label']} (top {card['cut']}) — {len(card['streaks'])} streaks, {n_players} players ==")
    for i, s in enumerate(card['streaks'][:6], 1):
        tag = '  <ACTIVE>' if s['active'] else ''
        print(f"  {i}  {s['name']:14s} {s['len']}  ({s['span'][0]}->{s['span'][1]}){tag}")
