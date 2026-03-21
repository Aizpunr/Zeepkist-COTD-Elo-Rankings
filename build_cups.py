import openpyxl, json, re, sys
sys.stdout.reconfigure(encoding='utf-8')

# ── 1. Parse Map Index from Lexer's spreadsheet ──
wb = openpyxl.load_workbook('Zeepkist COTD Results lexer original 23-02.xlsx', data_only=True)
ws = wb['Map Index']
rows = list(ws.iter_rows(values_only=True))

map_index = {}

for r in rows[3:]:
    # Regular COTDs: col 0=num, 2=mapper, 3=map
    if isinstance(r[0], int):
        key = f'COTD {r[0]}'
        map_index[key] = {
            'map': str(r[3]).strip() if r[3] else '',
            'mapper': str(r[2]).strip() if r[2] else ''
        }
    # Troll cups: col 8=label, 10=mapper, 11=map
    if r[8] and str(r[8]).strip() not in ('COTD #', ''):
        troll_str = str(r[8]).strip()
        m = re.match(r'Troll\s+(\d+)', troll_str)
        if m:
            key = f'Troll COTD {m.group(1)}'
            map_index[key] = {
                'map': str(r[11]).strip() if r[11] else '',
                'mapper': str(r[10]).strip() if r[10] else ''
            }

# ── 2. Add special cups manually ──
map_index['COTD Roulette 1'] = {'map': 'All previous cup maps on shuffle (Cups #1-24)', 'mapper': ''}
map_index['COTD Roulette 2'] = {'map': 'All previous cup maps on shuffle (Cups #1-65)', 'mapper': ''}
map_index['Troll COTW 9']    = {'map': 'Cheese of the Week!', 'mapper': 'Lexer'}
map_index['COTD 133']        = {'map': "Serpent's Lair", 'mapper': '[CTR]Rourie13'}
map_index['COTD 134']        = {'map': 'Urbs Noctu', 'mapper': '[20x]K410K3N'}
map_index['COTD 135']        = {'map': 'Hypnerotomachia', 'mapper': '[CSC] Sahne mit Bohnen'}

# ── Display aliases: shared accounts where ELO goes to real player ──
# Format: (cup_id, real_player) → display_name
# The account name shows in cups view; ELO is calculated under real_player
DISPLAY_ALIASES = {
    ('COTD 133', 'Kernkob'): 'rtm_lover2007',
}

# ── Hidden from cup view: real players whose ELO is credited via ghost ──
# Ghost player already appears naturally from their own history entry
# Ghost uses real player's rating_after for tier color (so it doesn't look like a smurf)
HIDDEN_FROM_CUP = {
    ('COTD 133', 'Kernkob'):  'rtm_lover2007',
}

# ── 3. Invert player history into cup-centric data ──
with open('elo_results_75.json', encoding='utf-8') as f:
    elo = json.load(f)

cups = {}  # cup_id -> {players: [...], lobby_size, map, mapper}

for player in elo['leaderboard']:
    for h in player['history']:
        cid = h['cup']
        if cid not in cups:
            cups[cid] = {'players': [], 'lobby_size': h['lobby_size']}
        cups[cid]['players'].append({
            'pos': h['position'],
            'name': player['name'],
            'rating_after': h['rating']
        })

# Sort players by position within each cup
for cid in cups:
    cups[cid]['players'].sort(key=lambda p: p['pos'])

# ── 4. Build ordered output using same sort as elo_75.py ──
SPECIAL_CUP_ORDER = {
    'COTD Roulette 1': 25.5, 'COTD Roulette 2': 65.5,
    'Troll COTD 1': 15.5, 'Troll COTD 2': 26.5, 'Troll COTD 3': 36.5,
    'Troll COTD 4': 41.5, 'Troll COTD 5': 44.5, 'Troll COTD 6': 48.5,
    'Troll COTD 7': 50.5, 'Troll COTD 8': 56.5, 'Troll COTW 9': 63.5,
    'Troll COTD 10': 71.5, 'Troll COTD 11': 88.5,
}
def cup_sort_key(cid):
    if cid in SPECIAL_CUP_ORDER: return SPECIAL_CUP_ORDER[cid]
    m = re.search(r'(\d+)', cid)
    return int(m.group(1)) if m else 0

result = []
for cid in sorted(cups.keys(), key=cup_sort_key):
    meta = map_index.get(cid, {'map': '', 'mapper': ''})
    players = cups[cid]['players']
    # Hide real players whose ELO is credited via ghost system
    # Give the ghost the real player's rating for tier color
    for hidden_key, ghost_name in HIDDEN_FROM_CUP.items():
        if hidden_key[0] != cid:
            continue
        real_name = hidden_key[1]
        real_rating = next((p['rating_after'] for p in players if p['name'] == real_name), None)
        if real_rating is not None:
            for p in players:
                if p['name'] == ghost_name:
                    p['rating_after'] = -real_rating  # negative = hidden, abs for color
    players = [p for p in players if (cid, p['name']) not in HIDDEN_FROM_CUP]
    # Apply display aliases (shared accounts)
    for p in players:
        alias_key = (cid, p['name'])
        if alias_key in DISPLAY_ALIASES:
            p['name'] = DISPLAY_ALIASES[alias_key]
    result.append({
        'id': cid,
        'map': meta['map'],
        'mapper': meta['mapper'],
        'lobby_size': cups[cid]['lobby_size'],
        'players': players
    })

# ── 5. Compute cup strength (SOF%) ──
POOL_CAP = 196
running = {}   # name -> latest known rating (from prior cups)
pre_norm = []  # pre_norm[i] = normalized pool BEFORE cup i

for i, cup in enumerate(result):
    # Build normalized pool from ratings known so far (pre-cup state)
    entries = sorted(running.items(), key=lambda x: x[1], reverse=True)
    pool = entries[:POOL_CAP]
    norm = {}
    if pool:
        max_r = pool[0][1]
        scale = 2000 / max_r
        for name, rating in pool:
            norm[name] = rating * scale
    pre_norm.append(norm)
    # Update running pool with this cup's results
    for p in cup['players']:
        running[p['name']] = abs(p['rating_after'])

# Cups 0-9 use the cup 10 snapshot for stability (too few data points early on)
early = pre_norm[10] if len(pre_norm) > 10 else pre_norm[-1]
rank_maps = [early if i < 10 else pre_norm[i] for i in range(len(result))]

for i, cup in enumerate(result):
    norm_map = rank_maps[i]
    if len(norm_map) < 2:
        cup['strength'] = 0
        continue
    elos = sorted(
        [norm_map[p['name']] for p in cup['players'] if p['name'] in norm_map],
        reverse=True
    )[:10]
    if not elos:
        cup['strength'] = 0
        continue
    min_pool = min(norm_map.values())
    while len(elos) < 10:
        elos.append(min_pool)
    avg = sum(elos) / len(elos)
    cup['strength'] = round(avg / 1850 * 100, 1)

with open('cups.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, separators=(',', ':'))

print(f'Done. {len(result)} cups written to cups.json')
for c in result[:3]:
    print(f"  {c['id']}: {c['map']} by {c['mapper']} — {len(c['players'])} players")
