"""
build_altrank.py — Alternative Rankings: TrueSkill + Glicko-2 from scratch.

Two completely independent rating systems, both adapted for free-for-all cups.
No pip dependencies — pure Python + math.

Outputs altrank_data.json and altrank_snapshot.json for altrank.html.
"""
import openpyxl, json, re, sys, os, math
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

base = os.path.dirname(os.path.abspath(__file__))
def _p(f): return os.path.join(base, f)

# ── Aliases (eval from elo_engine.py source) ──────────────────────────────

def load_aliases():
    name_map = {}
    canonical = {}
    lines = open(_p('elo_engine.py'), encoding='utf-8').readlines()
    collecting = False
    buf = []
    for line in lines:
        if not collecting and re.match(r'^CANONICAL\s*=\s*\{', line):
            collecting = True
        if collecting:
            buf.append(line)
            if line.strip() == '}':
                break
    if buf:
        block = ''.join(buf).split('=', 1)[1].strip()
        canonical = eval(block)
        for canon, aliases in canonical.items():
            for alias in aliases:
                name_map[alias] = canon
    return name_map, canonical

NAME_MAP, CANONICAL = load_aliases()

def strip_tag(name):
    return re.sub(r'\[.*?\]\s*', '', name).strip()

def normalize(name):
    if name in NAME_MAP:
        return NAME_MAP[name]
    stripped = strip_tag(name)
    if stripped in NAME_MAP:
        return NAME_MAP[stripped]
    if stripped != name and stripped in CANONICAL:
        return stripped
    return name

# ── Parsers (from elo_engine.py) ──────────────────────────────────────────

def parse_file(filepath):
    try:
        wb = openpyxl.load_workbook(filepath, data_only=True)
    except FileNotFoundError:
        print(f"  SKIP: {filepath} not found")
        return []
    cups = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        position_cells = []
        for ri, row in enumerate(rows):
            for ci, val in enumerate(row):
                if val == 'Position':
                    position_cells.append((ri, ci))
        for pos_row, pos_col in position_cells:
            cup_name = None
            for sr in range(pos_row - 1, max(pos_row - 5, -1), -1):
                val = rows[sr][pos_col] if pos_col < len(rows[sr]) else None
                if val and (str(val).startswith('COTD') or str(val).startswith('COTW')):
                    cup_name = str(val).strip()
                    break
            if not cup_name: continue
            players = []
            last_pos = None
            for row in rows[pos_row + 1:]:
                if pos_col >= len(row) or pos_col + 1 >= len(row): continue
                pos, name = row[pos_col], row[pos_col + 1]
                if name is None: continue
                name_str = str(name).strip()
                if name_str.startswith('*'): continue
                if pos is not None:
                    try:
                        pos_clean = str(pos).rstrip('*').strip()
                        last_pos = int(float(pos_clean))
                        players.append((last_pos, name_str))
                    except: continue
                elif last_pos is not None:
                    players.append((last_pos, name_str))
            if players:
                cups.append({'name': cup_name, 'players': sorted(players, key=lambda x: x[0])})
    return cups

def parse_troll_cups(filepath):
    wb = openpyxl.load_workbook(filepath, data_only=True)
    ws = wb['Troll COTDs']
    rows = list(ws.iter_rows(values_only=True))
    troll_defs = [
        ('Troll COTD 1', 15.5, 0), ('Troll COTD 2', 26.5, 6),
        ('Troll COTD 3', 36.5, 12), ('Troll COTD 4', 41.5, 17),
        ('Troll COTD 5', 44.5, 23), ('Troll COTD 6', 48.5, 29),
        ('Troll COTD 7', 50.5, 35), ('Troll COTD 8', 56.5, 41),
        ('Troll COTW 9', 63.5, 47), ('Troll COTD 10', 71.5, 53),
        ('Troll COTD 11', 88.5, 59),
    ]
    troll4_override = [
        (1, 'justMaki'), (2, 'Mark'), (3, 'Lexer'),
        (3, '[CTR]R0nanC'), (3, 'ButItRuns'), (3, 'St Nicholas'), (3, 'Hi Im Yolo'),
        (3, 'RoundNzt'), (3, '[CTR]L3it3R'), (3, 'FINSTER83'), (3, 'Neb'),
        (3, '[CTR]Hydro'), (3, '[RTR]Fwogiie'), (3, '[heyo]Mr. Hubub'), (3, 'agix'),
        (3, 'koz'), (3, '[6dog] schmxrg'), (3, 'Lynhardt'),
    ]
    cups = []
    for name, order, pc in troll_defs:
        players = []
        for row in rows[5:]:
            if pc >= len(row) or pc+1 >= len(row): continue
            pos, nm = row[pc], row[pc+1]
            if pos is None or nm is None: continue
            nm = str(nm).strip()
            if 'Other Player' in nm: continue
            nm = nm.replace('[CTR[', '[CTR]').replace('[RTR[', '[RTR]')
            try: players.append((int(float(pos)), nm))
            except: continue
        if len(players) >= 2:
            cups.append({'name': name, 'players': sorted(players, key=lambda x: x[0])})
        if name == 'Troll COTD 4':
            cups[-1 if cups and cups[-1]['name'] == 'Troll COTD 4' else len(cups):] = []
            cups.append({'name': name, 'players': troll4_override})
    return cups

# ── Cup loading + normalization ───────────────────────────────────────────

# Read xlsx file list from elo_engine.py source
elo_src = open(_p('elo_engine.py'), encoding='utf-8').read()
xlsx_files = re.findall(r"parse_file\(_p\('(.+?\.xlsx)'\)\)", elo_src)
xlsx_files = [f for f in xlsx_files if 'Troll' not in f and 'roulette' not in f.lower()]

print("Loading cups...")
all_cups = []
for xlsx in xlsx_files:
    all_cups += parse_file(_p(xlsx))

# Roulette + troll cups
roulette_files = [f for f in re.findall(r"parse_file\(_p\('(.+?\.xlsx)'\)\)", elo_src)
                  if 'roulette' in f.lower()]
for f in roulette_files:
    all_cups += parse_file(_p(f))

troll_files = re.findall(r"parse_troll_cups\(_p\('(.+?\.xlsx)'\)\)", elo_src)
for f in troll_files:
    all_cups += parse_troll_cups(_p(f))

SPECIAL_CUP_ORDER = {
    'COTD Roulette 1': 25.5, 'COTD Roulette 2': 65.5,
    'Troll COTD 1': 15.5, 'Troll COTD 2': 26.5,
    'Troll COTD 3': 36.5, 'Troll COTD 4': 41.5,
    'Troll COTD 5': 44.5, 'Troll COTD 6': 48.5,
    'Troll COTD 7': 50.5, 'Troll COTD 8': 56.5,
    'Troll COTW 9': 63.5, 'Troll COTD 10': 71.5,
    'Troll COTD 11': 88.5,
}

def cup_num(name):
    if name in SPECIAL_CUP_ORDER: return SPECIAL_CUP_ORDER[name]
    m = re.search(r'(\d+)', name)
    return int(m.group(1)) if m else 0

all_cups.sort(key=lambda c: cup_num(c['name']))

# Deduplicate
seen = set()
deduped = []
for c in all_cups:
    n = cup_num(c['name'])
    if n not in seen:
        seen.add(n)
        deduped.append(c)
all_cups = deduped

def is_nonstandard(cup_name):
    return cup_name.startswith('Troll ') or 'Roulette' in cup_name

pure_cups = [c for c in all_cups if not is_nonstandard(c['name'])]
print(f"Loaded {len(all_cups)} cups ({len(pure_cups)} pure)")

# COTD 16 fix: both finalists DNF'd — tied at 2nd
for c in all_cups:
    if c['name'] == 'COTD 16':
        c['players'] = [(2 if pos == 1 else pos, name) for pos, name in c['players']]
        break

# Normalize names
for cup in all_cups:
    cup['players'] = [(pos, normalize(name)) for pos, name in cup['players']]

# Ghost handling: "account_name (elo=RealPlayer)"
for cup in all_cups:
    new_players = []
    for pos, name in cup['players']:
        m = re.match(r'^(.+?)\s*\(elo=(.+?)\)$', name)
        if m:
            real_name = normalize(m.group(2).strip())
            new_players.append((pos, real_name))
        else:
            new_players.append((pos, name))
    cup['players'] = new_players

unique = set(name for cup in all_cups for _, name in cup['players'])
print(f"Unique players: {len(unique)}")

# ═══════════════════════════════════════════════════════════════════════════
# TRUESKILL — from scratch
# ═══════════════════════════════════════════════════════════════════════════

# Gaussian math
def norm_pdf(x):
    return math.exp(-x * x / 2) / math.sqrt(2 * math.pi)

def norm_cdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))

def v_func(t, eps=0):
    """Truncated Gaussian mean correction (win case)."""
    denom = norm_cdf(t - eps)
    if denom < 1e-10:
        return -t + eps
    return norm_pdf(t - eps) / denom

def w_func(t, eps=0):
    """Truncated Gaussian variance correction (win case)."""
    v = v_func(t, eps)
    return v * (v + t - eps)

# Constants
TS_MU0 = 25.0
TS_SIGMA0 = TS_MU0 / 3          # 8.333
TS_BETA = TS_SIGMA0 / 2          # 4.167 — performance variance
TS_TAU = TS_SIGMA0 / 100         # 0.0833 — dynamics factor (sigma drift per cup)
TS_SIGMA_FLOOR = 0.5             # minimum sigma to prevent collapse
TS_DISPLAY_SCALE = 40.0          # maps native → 1500 range
TS_DISPLAY_BASE = 1500.0

def ts_display(mu, sigma):
    """Scale TrueSkill conservative rating (mu - 3σ) to 1500 range."""
    return round(TS_DISPLAY_BASE + (mu - 3 * sigma) * TS_DISPLAY_SCALE, 1)

def compute_trueskill(cups):
    ts = {}  # name → (mu, sigma)
    gp = defaultdict(int)
    history = defaultdict(list)
    wins = defaultdict(int)
    pods = defaultdict(lambda: [0, 0, 0])
    best = defaultdict(lambda: 999)
    total_pos = defaultdict(int)
    avg_cups = defaultdict(int)
    peak = defaultdict(lambda: -9999)

    for cup in cups:
        players = cup['players']
        n = len(players)
        if n < 2: continue

        # Sigma drift for all known players (inactivity increases uncertainty)
        for name in ts:
            mu, sigma = ts[name]
            ts[name] = (mu, min(math.sqrt(sigma**2 + TS_TAU**2), TS_SIGMA0))

        # Initialize new players
        for _, name in players:
            if name not in ts:
                ts[name] = (TS_MU0, TS_SIGMA0)

        # All pairwise updates, scaled by 1/(N-1)
        delta_mu = defaultdict(float)
        delta_sig2 = defaultdict(float)

        for i in range(n):
            pi, ni = players[i]
            mu_i, sig_i = ts[ni]
            for j in range(n):
                if i == j: continue
                pj, nj = players[j]
                mu_j, sig_j = ts[nj]
                c = math.sqrt(2 * TS_BETA**2 + sig_i**2 + sig_j**2)
                t = (mu_i - mu_j) / c

                if pi < pj:       # i beat j
                    v = v_func(t)
                    w = w_func(t)
                elif pi > pj:     # j beat i
                    v = -v_func(-t)
                    w = w_func(-t)
                else:             # tie — skip
                    continue

                delta_mu[ni] += (sig_i**2 / c) * v / (n - 1)
                delta_sig2[ni] -= (sig_i**4 / c**2) * w / (n - 1)

        # Apply updates + track stats
        for pos, name in players:
            mu, sigma = ts[name]
            mu += delta_mu[name]
            sigma = math.sqrt(max(sigma**2 + delta_sig2[name], TS_SIGMA_FLOOR**2))
            ts[name] = (mu, sigma)

            display = ts_display(mu, sigma)
            gp[name] += 1
            history[name].append({'cup': cup['name'], 'position': pos,
                                  'rating': display, 'lobby_size': n})
            if display > peak[name]:
                peak[name] = display

            is_troll4_dnf = cup['name'] == 'Troll COTD 4' and pos == 3
            if not is_troll4_dnf:
                total_pos[name] += pos
                avg_cups[name] += 1
                if pos < best[name]: best[name] = pos
            if pos == 1: wins[name] += 1; pods[name][0] += 1
            elif pos == 2: pods[name][1] += 1
            elif pos == 3 and not is_troll4_dnf: pods[name][2] += 1

    # Build ratings + uncertainty dicts
    ratings = {}
    uncertainty = {}
    for name in ts:
        mu, sigma = ts[name]
        ratings[name] = ts_display(mu, sigma)
        uncertainty[name] = round(sigma * TS_DISPLAY_SCALE, 1)

    return {'ratings': ratings, 'uncertainty': uncertainty,
            'gp': gp, 'history': history, 'wins': wins,
            'pods': pods, 'best': best, 'total_pos': total_pos, 'avg_cups': avg_cups,
            'peak': peak}


# ═══════════════════════════════════════════════════════════════════════════
# GLICKO-2 — from scratch
# ═══════════════════════════════════════════════════════════════════════════

G2_R0 = 1500.0
G2_RD0 = 350.0
G2_VOL0 = 0.06
G2_TAU = 0.5                    # system constant
G2_EPSILON = 0.000001           # convergence tolerance
G2_SCALE = 173.7178             # 400 / ln(10)
G2_MAX_ITER = 100

def g2_to_mu(r): return (r - 1500) / G2_SCALE
def g2_to_phi(rd): return rd / G2_SCALE
def g2_from_mu(mu): return mu * G2_SCALE + 1500
def g2_from_phi(phi): return phi * G2_SCALE

def g2_g(phi):
    return 1.0 / math.sqrt(1 + 3 * phi**2 / (math.pi**2))

def g2_E(mu, mu_j, phi_j):
    x = -g2_g(phi_j) * (mu - mu_j)
    if x > 700: return 0.0
    if x < -700: return 1.0
    return 1.0 / (1 + math.exp(x))

def g2_new_volatility(sigma, phi, delta, v):
    """Glicko-2 step 5: iterative volatility update (Illinois algorithm)."""
    a = math.log(sigma**2)
    tau2 = G2_TAU**2

    def f(x):
        ex = math.exp(x)
        d2 = delta**2
        p2v = phi**2 + v + ex
        return (ex * (d2 - phi**2 - v - ex)) / (2 * p2v**2) - (x - a) / tau2

    # Bracket
    A = a
    if delta**2 > phi**2 + v:
        B = math.log(delta**2 - phi**2 - v)
    else:
        k = 1
        while f(a - k * G2_TAU) < 0 and k < G2_MAX_ITER:
            k += 1
        B = a - k * G2_TAU

    fA = f(A)
    fB = f(B)
    for _ in range(G2_MAX_ITER):
        if abs(B - A) < G2_EPSILON:
            break
        C = A + (A - B) * fA / (fB - fA)
        fC = f(C)
        if fC * fB <= 0:
            A = B; fA = fB
        else:
            fA /= 2
        B = C; fB = fC

    return math.exp(A / 2)


def compute_glicko2(cups):
    # State: name → (rating, RD, volatility) in Glicko-1 scale
    state = {}
    gp = defaultdict(int)
    history = defaultdict(list)
    wins = defaultdict(int)
    pods = defaultdict(lambda: [0, 0, 0])
    best = defaultdict(lambda: 999)
    total_pos = defaultdict(int)
    avg_cups = defaultdict(int)
    peak_rating = defaultdict(lambda: -9999)

    for cup in cups:
        players = cup['players']
        n = len(players)
        if n < 2: continue

        # RD growth for inactive players (natural Glicko-2 inactivity)
        for name in state:
            r, rd, vol = state[name]
            phi = g2_to_phi(rd)
            phi_star = math.sqrt(phi**2 + vol**2)
            new_rd = min(g2_from_phi(phi_star), G2_RD0)
            state[name] = (r, new_rd, vol)

        # Initialize new players
        for _, name in players:
            if name not in state:
                state[name] = (G2_R0, G2_RD0, G2_VOL0)

        # Compute updates for each player in the cup
        new_states = {}
        for i in range(n):
            pi, ni = players[i]
            r_i, rd_i, vol_i = state[ni]
            mu_i = g2_to_mu(r_i)
            phi_i = g2_to_phi(rd_i)

            # Pairwise against all opponents, scaled by 1/(N-1) to normalize FFA
            v_sum = 0
            delta_sum = 0
            weight = 1.0 / (n - 1)
            for j in range(n):
                if i == j: continue
                pj, nj = players[j]
                r_j, rd_j, _ = state[nj]
                mu_j = g2_to_mu(r_j)
                phi_j = g2_to_phi(rd_j)

                gj = g2_g(phi_j)
                ej = g2_E(mu_i, mu_j, phi_j)
                v_sum += weight * gj**2 * ej * (1 - ej)

                s = 1.0 if pi < pj else (0.0 if pi > pj else 0.5)
                delta_sum += weight * gj * (s - ej)

            v = 1.0 / v_sum if v_sum > 1e-10 else 1e6
            delta = v * delta_sum

            # New volatility
            new_vol = g2_new_volatility(vol_i, phi_i, delta, v)

            # New phi and mu
            phi_star = math.sqrt(phi_i**2 + new_vol**2)
            new_phi = 1.0 / math.sqrt(1 / phi_star**2 + 1 / v)
            new_mu = mu_i + new_phi**2 * delta_sum

            new_r = round(g2_from_mu(new_mu), 1)
            new_rd = g2_from_phi(new_phi)
            new_states[ni] = (new_r, new_rd, new_vol)

        # Apply updates + track stats
        for pos, name in players:
            if name in new_states:
                state[name] = new_states[name]
            r = state[name][0]

            gp[name] += 1
            history[name].append({'cup': cup['name'], 'position': pos,
                                  'rating': round(r, 1), 'lobby_size': n})
            if r > peak_rating[name]:
                peak_rating[name] = r

            is_troll4_dnf = cup['name'] == 'Troll COTD 4' and pos == 3
            if not is_troll4_dnf:
                total_pos[name] += pos
                avg_cups[name] += 1
                if pos < best[name]: best[name] = pos
            if pos == 1: wins[name] += 1; pods[name][0] += 1
            elif pos == 2: pods[name][1] += 1
            elif pos == 3 and not is_troll4_dnf: pods[name][2] += 1

    ratings = {name: round(state[name][0], 1) for name in state}
    uncertainty = {name: round(state[name][1], 1) for name in state}

    return {'ratings': ratings, 'uncertainty': uncertainty,
            'gp': gp, 'history': history, 'wins': wins,
            'pods': pods, 'best': best, 'total_pos': total_pos, 'avg_cups': avg_cups,
            'peak': peak_rating}


# ═══════════════════════════════════════════════════════════════════════════
# OUTPUT
# ═══════════════════════════════════════════════════════════════════════════

DECAY = 0.995
GRACE = 3

def build_all_list(elo_data, cups_list, min_cups=1):
    rat = elo_data['ratings']
    unc_d = elo_data['uncertainty']
    hist = elo_data['history']
    gp_d = elo_data['gp']
    best_d = elo_data['best']
    total_pos_d = elo_data['total_pos']
    avg_cups_d = elo_data['avg_cups']
    wins_d = elo_data['wins']
    pods_d = elo_data['pods']
    peak_d = elo_data['peak']

    total_n = len(cups_list)
    last_idx = {}
    for idx, cup in enumerate(cups_list):
        for _, name in cup['players']:
            last_idx[name] = idx

    def dec(rating, name):
        missed = total_n - 1 - last_idx.get(name, 0)
        if missed <= GRACE: return round(rating, 1)
        return round(1500 + (rating - 1500) * (DECAY ** (missed - GRACE)), 1)

    out = []
    for name in rat:
        has_pod = sum(pods_d[name]) > 0
        if gp_d[name] < min_cups and not has_pod: continue
        raw = round(rat[name], 1)
        act = dec(rat[name], name)
        avg = round(total_pos_d[name] / avg_cups_d[name], 1) if avg_cups_d[name] > 0 else 0
        pk = peak_d.get(name, raw)
        h_list = [{'c': cup_num(h['cup']), 'r': h['rating'], 'p': h['position']}
                  for h in hist[name]]
        out.append({
            'n': name, 'a': act, 'r': raw, 'u': unc_d.get(name, 0),
            'c': gp_d[name], 'b': best_d[name] if best_d[name] < 999 else 0,
            'v': avg, 'w': wins_d[name],
            'g': pods_d[name][0], 's': pods_d[name][1], 'z': pods_d[name][2],
            'p': round(pk, 1), 'h': h_list
        })
    out.sort(key=lambda p: p['a'], reverse=True)
    return out

# ── Compute ───────────────────────────────────────────────────────────────

print("\nComputing TrueSkill (all cups)...")
ts_full = compute_trueskill(all_cups)
print("Computing TrueSkill (pure cups)...")
ts_pure = compute_trueskill(pure_cups)

print("Computing Glicko-2 (all cups)...")
g2_full = compute_glicko2(all_cups)
print("Computing Glicko-2 (pure cups)...")
g2_pure = compute_glicko2(pure_cups)

# ── Build JSON ────────────────────────────────────────────────────────────

altdata = {
    'trueskill':      build_all_list(ts_full, all_cups),
    'trueskill_pure': build_all_list(ts_pure, pure_cups),
    'glicko2':        build_all_list(g2_full, all_cups),
    'glicko2_pure':   build_all_list(g2_pure, pure_cups),
}

with open(_p('altrank_data.json'), 'w') as f:
    json.dump(altdata, f, separators=(',', ':'))

size_kb = os.path.getsize(_p('altrank_data.json')) / 1024
print(f"\naltrank_data.json written ({size_kb:.0f} KB)")

# ── Snapshot ──────────────────────────────────────────────────────────────

def build_snapshot(player_list, min_cups=5):
    entries = []
    for p in player_list:
        if p['c'] < min_cups and (p['g'] + p['s'] + p['z']) == 0:
            continue
        entries.append((p['n'], p['a'], p['w'], p['g'] + p['s'] + p['z']))
    entries.sort(key=lambda x: x[1], reverse=True)
    return {name: [i + 1, act, w, pd] for i, (name, act, w, pd) in enumerate(entries[:150])}

snap = {
    'ts':      build_snapshot(altdata['trueskill']),
    'g2':      build_snapshot(altdata['glicko2']),
    'ts_pure': build_snapshot(altdata['trueskill_pure']),
    'g2_pure': build_snapshot(altdata['glicko2_pure']),
}

with open(_p('altrank_snapshot.json'), 'w') as f:
    json.dump(snap, f, separators=(',', ':'))
print("altrank_snapshot.json written")

# ── Sanity check ──────────────────────────────────────────────────────────

for label, data in [('TrueSkill', altdata['trueskill']), ('Glicko-2', altdata['glicko2'])]:
    top5 = data[:5]
    print(f"\n{label} top 5:")
    for i, p in enumerate(top5):
        print(f"  {i+1}. {p['n']:20s}  {p['a']:.1f}  ({p['c']} cups, {p['w']} wins)")
