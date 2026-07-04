import openpyxl, json, re, sys, os, datetime
sys.stdout.reconfigure(encoding='utf-8')

# Anchor all paths to this file's directory — running from another cwd used to
# crash on 'cup logs' / write cups.json into the wrong place.
_dir = os.path.dirname(os.path.abspath(__file__))
_p = lambda f: os.path.join(_dir, f)

# ── Cup dates ──
# Source of truth for cup dates. New cups (not in this dict) auto-resolve
# from the cup-log mtime (cup logs/cotd_<N>.log). Add new cups here once
# they're stable so the date doesn't depend on the log file sticking around.
CUP_DATES = {
    'COTD 1': '2023-03-05', 'COTD 2': '2023-03-12', 'COTD 3': '2023-03-24',
    'COTD 4': '2023-04-01', 'COTD 5': '2023-04-07', 'COTD 6': '2023-04-15',
    'COTD 7': '2023-04-22', 'COTD 8': '2023-04-29', 'COTD 9': '2023-05-06',
    'COTD 10': '2023-05-12', 'COTD 11': '2023-05-20', 'COTD 12': '2023-05-27',
    'COTD 13': '2023-06-04', 'COTD 14': '2023-06-11', 'COTD 15': '2023-06-16',
    'COTD 16': '2023-06-23', 'COTD 17': '2023-07-01', 'COTD 18': '2023-07-08',
    'COTD 19': '2023-07-15', 'COTD 20': '2023-07-23', 'COTD 21': '2023-07-30',
    'COTD 22': '2023-08-06', 'COTD 23': '2023-08-13', 'COTD 24': '2023-08-19',
    'COTD 25': '2023-09-03', 'COTD 26': '2023-09-17', 'COTD 27': '2023-09-24',
    'COTD 28': '2023-10-07', 'COTD 29': '2023-10-28', 'COTD 30': '2023-11-05',
    'COTD 31': '2023-11-10', 'COTD 32': '2023-11-17', 'COTD 33': '2023-11-26',
    'COTD 34': '2023-12-03', 'COTD 35': '2023-12-10', 'COTD 36': '2023-12-16',
    'COTD 37': '2024-01-13', 'COTD 38': '2024-01-20', 'COTD 39': '2024-01-27',
    'COTD 40': '2024-02-11', 'COTD 41': '2024-02-17', 'COTD 42': '2024-03-03',
    'COTD 43': '2024-03-10', 'COTD 44': '2024-03-17', 'COTD 45': '2024-03-30',
    'COTD 46': '2024-04-07', 'COTD 47': '2024-04-20', 'COTD 48': '2024-04-27',
    'COTD 49': '2024-05-11', 'COTD 50': '2024-05-25', 'COTD 51': '2024-06-09',
    'COTD 52': '2024-06-15', 'COTD 53': '2024-06-29', 'COTD 54': '2024-07-06',
    'COTD 55': '2024-07-13', 'COTD 56': '2024-07-20', 'COTD 57': '2024-08-03',
    'COTD 58': '2024-08-10',
    'COTD 59': '2024-08-17', 'COTD 60': '2024-08-24', 'COTD 61': '2024-08-31',
    'COTD 62': '2024-09-07', 'COTD 63': '2024-09-14', 'COTD 64': '2024-09-28',
    'COTD 65': '2024-10-05',
    'COTD 66': '2024-10-19', 'COTD 67': '2024-10-26',
    'COTD 68': '2024-11-02', 'COTD 69': '2024-11-09', 'COTD 70': '2024-11-16',
    'COTD 71': '2024-11-23', 'COTD 72': '2024-12-07', 'COTD 73': '2024-12-14',
    'COTD 74': '2024-12-21', 'COTD 75': '2025-01-04', 'COTD 76': '2025-01-11',
    'COTD 77': '2025-01-18', 'COTD 78': '2025-01-25', 'COTD 79': '2025-02-01',
    'COTD 80': '2025-02-08', 'COTD 81': '2025-03-09', 'COTD 82': '2025-03-09',
    'COTD 83': '2025-03-09', 'COTD 84': '2025-03-10', 'COTD 85': '2025-03-15',
    'COTD 86': '2025-03-22', 'COTD 87': '2025-03-29', 'COTD 88': '2025-04-05',
    'COTD 89': '2025-04-12', 'COTD 90': '2025-04-19', 'COTD 91': '2025-04-26',
    'COTD 92': '2025-05-03', 'COTD 93': '2025-05-10', 'COTD 94': '2025-05-17',
    'COTD 95': '2025-05-24', 'COTD 96': '2025-05-31', 'COTD 97': '2025-06-07',
    'COTD 98': '2025-06-14', 'COTD 99': '2025-06-28', 'COTD 100': '2025-07-05',
    'COTD 101': '2025-07-12', 'COTD 102': '2025-07-19', 'COTD 103': '2025-07-26',
    'COTD 104': '2025-08-02', 'COTD 105': '2025-08-09', 'COTD 106': '2025-08-16',
    'COTD 107': '2025-08-23', 'COTD 108': '2025-08-30', 'COTD 109': '2025-09-06',
    'COTD 110': '2025-09-13', 'COTD 111': '2025-09-20', 'COTD 112': '2025-09-27',
    'COTD 113': '2025-10-04', 'COTD 114': '2025-10-11', 'COTD 115': '2025-10-18',
    'COTD 116': '2025-10-25', 'COTD 117': '2025-11-01', 'COTD 118': '2025-11-08',
    'COTD 119': '2025-11-15', 'COTD 120': '2025-11-22', 'COTD 121': '2025-11-29',
    'COTD 122': '2025-12-06', 'COTD 123': '2025-12-13', 'COTD 124': '2025-12-20',
    'COTD 125': '2025-12-27', 'COTD 126': '2026-01-03', 'COTD 127': '2026-01-17',
    'COTD 128': '2026-01-24', 'COTD 129': '2026-01-31', 'COTD 130': '2026-02-07',
    'COTD 131': '2026-02-14', 'COTD 132': '2026-02-21', 'COTD 133': '2026-02-28',
    'COTD 134': '2026-03-07', 'COTD 135': '2026-03-14', 'COTD 136': '2026-03-21',
    'COTD 137': '2026-03-28', 'COTD 138': '2026-04-04', 'COTD 139': '2026-04-11',
    'COTD 140': '2026-04-18', 'COTD 141': '2026-04-25', 'COTD 142': '2026-05-02',
    'COTD 143': '2026-05-09', 'COTD 144': '2026-05-16', 'COTD 145': '2026-05-23',
    'COTD 146': '2026-05-30', 'COTD 147': '2026-06-06', 'COTD 148': '2026-06-13',
    'COTD 149': '2026-06-20', 'COTD 150': '2026-06-27',
    'COTD 151': '2026-07-04',
}

def cup_date(cid):
    if cid in CUP_DATES:
        return CUP_DATES[cid]
    m = re.search(r'\d+', cid)
    if not m:
        return None
    log_path = _p(os.path.join('cup logs', f'cotd_{m.group()}.log'))
    if os.path.exists(log_path):
        return datetime.date.fromtimestamp(os.path.getmtime(log_path)).isoformat()
    return None

# ── 1. Parse Map Index from Lexer's spreadsheet ──
wb = openpyxl.load_workbook(_p('Zeepkist COTD Results (lexer 23-02).xlsx'), data_only=True)
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
map_index['Troll COTD 9']    = {'map': 'Cheese of the Week!', 'mapper': 'Lexer'}
map_index['Troll COTD 12']   = {'map': 'COTD - Hangman', 'mapper': '[TOG]ioi8'}
map_index['COTD 133']        = {'map': "Serpent's Lair", 'mapper': '[CTR]Rourie13'}
map_index['COTD 134']        = {'map': 'Urbs Noctu', 'mapper': '[20x]K410K3N'}
map_index['COTD 135']        = {'map': 'Hypnerotomachia', 'mapper': '[CSC] Sahne mit Bohnen'}
map_index['COTD 136']        = {'map': 'Volcanic', 'mapper': '[TTR] Tigerplaysonpc'}
map_index['COTD 137']        = {'map': 'COTD - Out of Breath', 'mapper': 'Diabler'}
map_index['COTD 138']        = {'map': 'Niwashade', 'mapper': '[CTR]Mortishade'}
map_index['COTD 139']        = {'map': 'Tripe', 'mapper': 'JobW'}
map_index['COTD 140']        = {'map': 'Ice Field Arctic', 'mapper': '[CSC]ShyGirlyRaccoon'}
map_index['COTD 141']        = {'map': 'Farewell', 'mapper': 'PlusMicron'}
map_index['COTD 142']        = {'map': 'COTD - Slowtown', 'mapper': '[CSC] Shadynook'}
map_index['COTD 143']        = {'map': 'safe travels v4', 'mapper': 'crips.fourie'}
map_index['COTD 144']        = {'map': 'COTD 144 - Chartreuse Valley', 'mapper': '[CSC]Tommygaming'}
map_index['COTD 145']        = {'map': 'COTD - Resonance Ridge', 'mapper': 'Richhyyyy'}
map_index['COTD 146']        = {'map': 'Shambly COTD', 'mapper': '[CRT]Codewalt'}
map_index['COTD 147']        = {'map': 'COTD - Ashlands Descent', 'mapper': '[CSC]Mokster'}
map_index['COTD 148']        = {'map': 'Eleven Gallium', 'mapper': 'agix'}
map_index['COTD 149']        = {'map': 'The Spice Rack', 'mapper': '[CSC] OccasionallyAmazingGamer'}
map_index['COTD 150']        = {'map': 'Sink into Madness', 'mapper': 'Form'}
map_index['COTD 151']        = {'map': 'COTD - Greenslide', 'mapper': '[ZET]void'}

# ── 3. Invert player history into cup-centric data ──
with open(_p('elo_results.json'), encoding='utf-8') as f:
    elo = json.load(f)

# ── Ghost display: real player played under a ghost account ──
# cups.json keeps real player name + adds "ghost" field for frontend display.
# Format: (cup_id, real_player) → ghost_display_name
# Derived from elo_engine's ghost splits (the "account (elo=Real)" xlsx tags),
# exported in elo_results.json — this used to be a manual dict that silently
# shipped duplicate rows whenever a new ghost cup wasn't added to it.
GHOST_DISPLAY = {
    ('COTD 133', 'Kernkob'): 'rtm_lover2007',
    ('COTD 135', 'Sterben'): 'del gaming',
}
for _cid, _glist in elo.get('ghosts', {}).items():
    for _pos, _ghost, _real in _glist:
        key = (_cid, _real)
        if key not in GHOST_DISPLAY:
            print(f'Ghost auto-derived from elo_results.json: {key} -> {_ghost}')
        GHOST_DISPLAY[key] = _ghost

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

# ── 4. Build ordered output using same sort as elo_engine.py ──
SPECIAL_CUP_ORDER = {
    'COTD Roulette 1': 25.5, 'COTD Roulette 2': 65.5,
    'Troll COTD 1': 15.5, 'Troll COTD 2': 26.5, 'Troll COTD 3': 36.5,
    'Troll COTD 4': 41.5, 'Troll COTD 5': 44.5, 'Troll COTD 6': 48.5,
    'Troll COTD 7': 50.5, 'Troll COTD 8': 56.5, 'Troll COTW 9': 63.5,
    'Troll COTD 10': 71.5, 'Troll COTD 11': 88.5, 'Troll COTD 12': 144.5,
}
def cup_sort_key(cid):
    if cid in SPECIAL_CUP_ORDER: return SPECIAL_CUP_ORDER[cid]
    m = re.search(r'(\d+)', cid)
    return int(m.group(1)) if m else 0

result = []
for cid in sorted(cups.keys(), key=cup_sort_key):
    meta = map_index.get(cid, {'map': '', 'mapper': ''})
    players = cups[cid]['players']
    # Ghost handling: keep real player, add ghost field, remove ghost's shadow entry
    ghost_names_to_remove = set()
    for ghost_key, ghost_name in GHOST_DISPLAY.items():
        if ghost_key[0] != cid:
            continue
        real_name = ghost_key[1]
        for p in players:
            if p['name'] == real_name:
                p['ghost'] = ghost_name
        ghost_names_to_remove.add(ghost_name)
    players = [p for p in players if p['name'] not in ghost_names_to_remove]
    result.append({
        'id': cid,
        # Cups 59-65 were briefly branded "COTW"; normalize any lingering COTW
        # tag in old map titles (e.g. "Palm Freeze - COTW #60") to COTD.
        'map': meta['map'].replace('COTW', 'COTD'),
        'mapper': meta['mapper'],
        'date': cup_date(cid),
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
        running[p['name']] = p['rating_after']

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

with open(_p('cups.json'), 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, separators=(',', ':'))

print(f'Done. {len(result)} cups written to cups.json')
for c in result[:3]:
    print(f"  {c['id']}: {c['map']} by {c['mapper']} — {len(c['players'])} players")
