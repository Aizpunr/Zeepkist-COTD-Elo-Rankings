"""
new_cup.py — Automated cup processing from COTDTracker mod logs

Usage:
  python new_cup.py 135 "MapperName"

Parses mod logs, writes to xlsx + JSON backup, rebuilds all ELO data.
"""
import re, os, sys, json, subprocess
import openpyxl

# Force UTF-8 stdout so printing unicode aliases (e.g. the 𝒱V𝑜o𝒾i𝒹d𝒱 void name)
# in the alias-drift report can't crash the pipeline when stdout is redirected
# to a file (Windows defaults to cp1252, which can't encode those glyphs).
sys.stdout.reconfigure(encoding='utf-8')

_dir = os.path.dirname(os.path.abspath(__file__))
_p = lambda f: os.path.join(_dir, f)

LOG_PATH = r"C:\Program Files (x86)\Steam\steamapps\common\Zeepkist\BepInEx\LogOutput.log"
LIVE_LOG_PATH = r"C:\Program Files (x86)\Steam\steamapps\common\Zeepkist\BepInEx\LiveLeaderboardLogger.log"
COLS_PER_CUP = 6  # 4 data columns + 2 blank spacer

# ── Parse arguments ──
if len(sys.argv) < 3:
    print("Usage: python new_cup.py <cup_number> <mapper_name> [--exclude name1,name2,...]")
    print('Example: python new_cup.py 135 "[20x]K410K3N"')
    print('Example: python new_cup.py 141 "PlusMicron" --exclude justMaki')
    sys.exit(1)

cup_num = int(sys.argv[1])
mapper = sys.argv[2]
cup_id = f"COTD {cup_num}"

# Optional --exclude flag for playtesters or other non-cup players
extra_excluded = []
if '--exclude' in sys.argv:
    idx = sys.argv.index('--exclude')
    if idx + 1 < len(sys.argv):
        extra_excluded = [n.strip() for n in sys.argv[idx + 1].split(',') if n.strip()]

excluded = {mapper} | set(extra_excluded)

print(f"Processing {cup_id}, mapper: {mapper}")
if extra_excluded:
    print(f"Also excluding: {', '.join(extra_excluded)}")
print()

# ── 1. Save raw log + parse mod logs ──
log_dir = _p('cup logs')
os.makedirs(log_dir, exist_ok=True)
import shutil
log_backup = os.path.join(log_dir, f'cotd_{cup_num}.log')
shutil.copy2(LOG_PATH, log_backup)
print(f"Raw log saved: {log_backup}")
live_log_backup = os.path.join(log_dir, f'cotd_{cup_num}_liveleaderboard.log')
if os.path.exists(LIVE_LOG_PATH):
    shutil.copy2(LIVE_LOG_PATH, live_log_backup)
    print(f"Live log saved: {live_log_backup}")
else:
    print(f"⚠ Live log not found at {LIVE_LOG_PATH} — alias SID check will be skipped")
    live_log_backup = None

with open(LOG_PATH, encoding='utf-8', errors='replace') as f:
    lines = [l for l in f.readlines() if 'COTDTracker' in l]

if not lines:
    print("ERROR: No COTDTracker lines found in log file.")
    sys.exit(1)

rounds = []
current_round = []
for line in lines:
    if 'Doing eliminations with leaderboard' in line:
        if current_round:
            rounds.append(current_round)
        current_round = []
    elif 'Eliminating ' in line or 'Player ' in line:
        current_round.append(line)
if current_round:
    rounds.append(current_round)

if not rounds:
    print("ERROR: No elimination rounds found in log.")
    sys.exit(1)

# Build elimination order
# For each eliminated player, track:
#   display_time: their time in their elim round (or 'DNF' if they DNF'd it)
#   dnf:          True if they DNF'd their elimination round (determines tie)
#
# NOTE: display_time is ONLY from the elim round's own log entries. We used to
# fall back to last_known_time (some prior round's time) for DNFs, but that was
# misleading — it showed a time from a different round next to the round's
# elim number. DNFs now stay DNF.
elim_order = []
actual_round = 0
for rnd in rounds:
    player_times = {}
    eliminated_names = []
    for line in rnd:
        m = re.search(r'Player (.+?): Time: (.+)', line)
        if m:
            name = m.group(1).strip()
            time_str = m.group(2).strip()
            player_times[name] = time_str
        m2 = re.search(r'Eliminating (?:DNF|on time): (.+)', line)
        if m2:
            name = m2.group(1).strip()
            if name not in eliminated_names:
                eliminated_names.append(name)
    if not eliminated_names:
        continue
    actual_round += 1
    for name in eliminated_names:
        if name not in excluded:
            elim_round_time = player_times.get(name, 'DNF')
            dnf = (elim_round_time == 'DNF')
            elim_order.append((name, elim_round_time, actual_round, dnf))

# Find winner
all_named = set()
for rnd in rounds:
    for line in rnd:
        m = re.search(r'Player (.+?): Time:', line)
        if m:
            all_named.add(m.group(1).strip())
elim_set = {e[0] for e in elim_order}
winners = [n for n in all_named if n not in elim_set and n not in excluded]
if not winners:
    print("ERROR: Could not determine winner.")
    sys.exit(1)
winner = winners[0]

winner_time = None
for line in reversed(lines):
    m = re.search(r'Player ' + re.escape(winner) + r': Time: (.+)', line)
    if m:
        winner_time = m.group(1).strip()
        break

# Build leaderboard: within each elimination round, finishers get distinct
# positions ordered by their elim-round time (faster = better), then DNFs
# tie at the bottom of that round.
elim_order.reverse()
leaderboard = [(winner, winner_time, None, 1)]
pos = 2
i = 0
while i < len(elim_order):
    rnd = elim_order[i][2]
    group = []
    while i < len(elim_order) and elim_order[i][2] == rnd:
        group.append(elim_order[i])
        i += 1
    # Split by dnf flag — finishers get distinct positions by elim-round time,
    # DNFs (no valid time in elim round) all tie at the bottom of this round.
    finishers = []
    dnfs = []
    for name, display_time, r, dnf in group:
        if dnf:
            dnfs.append((name, display_time, r))
        else:
            try:
                t = float(str(display_time).replace(',', '.'))
                finishers.append((name, display_time, r, t))
            except (ValueError, TypeError):
                dnfs.append((name, display_time, r))
    finishers.sort(key=lambda x: x[3])
    for name, display_time, r, _ in finishers:
        leaderboard.append((name, display_time, r, pos))
        pos += 1
    if dnfs:
        dnf_pos = pos
        for name, display_time, r in dnfs:
            leaderboard.append((name, display_time, r, dnf_pos))
        pos += len(dnfs)

print(f"Parsed {len(leaderboard)} players (excluded: {', '.join(sorted(excluded))})")
print(f"Winner: {winner} ({winner_time})")
print(f"Rounds in log: {len(rounds)}")
print()

# Find fastest time. Round numbering matches the elim_order loop above:
# the first leaderboard with no eliminations is the discovery/warmup round (R0),
# Round 1 is the first round that actually eliminates someone.
fastest_time = None
fastest_name = None
fastest_round = None
actual_round = 0
for rnd in rounds:
    has_elim = any(re.search(r'Eliminating (?:DNF|on time):', line) for line in rnd)
    if has_elim:
        actual_round += 1
    rnd_num = actual_round if has_elim else 0
    for line in rnd:
        m = re.search(r'Player (.+?): Time: (.+)', line)
        if m:
            name = m.group(1).strip()
            time_str = m.group(2).strip()
            if time_str != 'DNF':
                t = float(time_str.replace(',', '.'))
                if fastest_time is None or t < fastest_time:
                    fastest_time = t
                    fastest_name = name
                    fastest_round = rnd_num

# ── 1b. Cross-check leaderboard names against livelog Steam IDs ──
# Catches alias drift: a player who joins a new clan and ends up tracked as a
# fresh identity (e.g. "[NewB]Zeus" → "[SLOW]Zeus" → "Zeus"). Same Steam ID =
# same player; mismatches between the lobby name and the canonical name in
# steam_ids.json get flagged with a copy-pasteable CANONICAL entry suggestion.
def check_aliases_against_livelog(leaderboard, live_log_path, steam_ids_path, canonical_src_path):
    if not live_log_path or not os.path.exists(live_log_path):
        print("⚠ ALIAS CHECK SKIPPED — no live log to read")
        return
    if not os.path.exists(steam_ids_path):
        print(f"⚠ ALIAS CHECK SKIPPED — no steam_ids.json at {steam_ids_path}")
        return
    # name -> SID from ROSTER lines
    roster = {}
    with open(live_log_path, encoding='utf-8-sig', errors='replace') as f:
        for line in f:
            mr = re.search(r'ROSTER\|(\d+)\|([^|]*)\|([^|]*)', line)
            if mr:
                sid = mr.group(1)
                for n in (mr.group(2).strip(), mr.group(3).strip()):
                    if n:
                        roster[n] = sid
    # SID -> canonical from steam_ids.json
    with open(steam_ids_path, encoding='utf-8') as f:
        sids = json.load(f)
    sid_to_canon = {v: k for k, v in sids.items()}
    # alias -> canonical from CANONICAL block in elo_engine.py
    with open(canonical_src_path, encoding='utf-8') as f:
        src = f.read()
    canon_block = re.search(r'CANONICAL\s*=\s*\{(.+?)^\}', src, re.MULTILINE | re.DOTALL)
    alias_to_canon, canon_names = {}, set()
    if canon_block:
        canon_dict = eval('{' + canon_block.group(1) + '}')
        canon_names = set(canon_dict.keys())
        for cn, aliases in canon_dict.items():
            for a in aliases:
                alias_to_canon[a] = cn

    drifts, new_players = [], []
    for entry in leaderboard:
        name = entry[0]
        sid = roster.get(name)
        if not sid:
            bare = re.sub(r'[\[\{].*?[\]\}]\s*', '', name).strip()
            sid = roster.get(bare)
        if not sid:
            continue
        canon_for_sid = sid_to_canon.get(sid)
        if canon_for_sid is None:
            new_players.append((name, sid))
            continue
        if name in alias_to_canon:
            resolved = alias_to_canon[name]
        elif name in canon_names or name == canon_for_sid:
            resolved = name if name in canon_names else canon_for_sid
        else:
            resolved = name  # would be tracked as the raw name = NOT merged
        if resolved != canon_for_sid:
            drifts.append((name, sid, canon_for_sid))

    if not drifts and not new_players:
        print("Alias check: all names match steam_ids.json canonicals ✓")
        return
    print()
    print("=" * 50)
    print("ALIAS CHECK — livelog SIDs vs steam_ids.json")
    print("=" * 50)
    if drifts:
        print(f"\n{len(drifts)} alias drift(s):")
        for name, sid, canon in drifts:
            print(f"  - {name!r} (sid {sid}) should map to canonical {canon!r}")
        print("\nUpdate CANONICAL in elo_engine.py — append these to the matching entry:")
        from collections import defaultdict
        by_canon = defaultdict(list)
        for name, _, canon in drifts:
            by_canon[canon].append(name)
        for canon, names in by_canon.items():
            names_lit = ', '.join(repr(n) for n in sorted(set(names)))
            print(f"  '{canon}': [..., {names_lit}],")
    if new_players:
        print(f"\n{len(new_players)} new player(s) — no entry in steam_ids.json:")
        for name, sid in new_players:
            print(f"  - {name!r} (sid {sid})")
        print("\nIf any are returning under a new name, add to steam_ids.json:")
        for name, sid in new_players:
            print(f'  "{name}": "{sid}",')
    print()

check_aliases_against_livelog(
    leaderboard,
    live_log_backup,
    _p('steam_ids.json'),
    _p('elo_engine.py'),
)

# ── 2. Auto-detect xlsx file + columns ──
elo_py_path = _p('elo_engine.py')
with open(elo_py_path, encoding='utf-8') as f:
    elo_src = f.read()

xlsx_matches = re.findall(r"parse_file\(_p\('(COTD \d+-\d+\.xlsx)'\)\)", elo_src)
if not xlsx_matches:
    print("ERROR: Could not find COTD xlsx reference in elo_engine.py")
    sys.exit(1)
current_xlsx = xlsx_matches[-1]
xlsx_path = _p(current_xlsx)

print(f"Current xlsx: {current_xlsx}")

wb = openpyxl.load_workbook(xlsx_path)
ws = wb[wb.sheetnames[0]]

# Find rightmost Position header to determine next column
rows = list(ws.iter_rows(values_only=True))
max_pos_col = 0
for ci, val in enumerate(rows[4]):  # Row 5 (0-indexed row 4) has headers
    if val == 'Position':
        max_pos_col = ci + 1  # Convert to 1-based

col_start = max_pos_col + COLS_PER_CUP
print(f"Last Position header at column {max_pos_col}, new cup at column {col_start}")

# ── 3. Write to xlsx ──
ws.cell(row=2, column=col_start, value=cup_id)
ws.cell(row=3, column=col_start, value=f'Map: {cup_id} by {mapper}')

if fastest_time is not None:
    ws.cell(row=4, column=col_start + 2,
            value=f'Fastest Time: {fastest_time:.3f} by {fastest_name} in Round {fastest_round}')

ws.cell(row=5, column=col_start, value='Position')
ws.cell(row=5, column=col_start + 1, value='Name')
ws.cell(row=5, column=col_start + 2, value='Elim Time')
ws.cell(row=5, column=col_start + 3, value='Elim Round')

for i, (name, time, rnd, position) in enumerate(leaderboard):
    row = 6 + i
    ws.cell(row=row, column=col_start, value=position)
    ws.cell(row=row, column=col_start + 1, value=name)
    if time == 'DNF':
        ws.cell(row=row, column=col_start + 2, value='DNF')
    else:
        t = float(time.replace(',', '.'))
        ws.cell(row=row, column=col_start + 2, value=round(t * 1000))
    if rnd is not None:
        ws.cell(row=row, column=col_start + 3, value=rnd)

# Rename xlsx if needed
m = re.match(r'COTD (\d+)-(\d+)\.xlsx', current_xlsx)
if m:
    start_num, end_num = int(m.group(1)), int(m.group(2))
    if cup_num > end_num:
        new_xlsx = f'COTD {start_num}-{cup_num}.xlsx'
        new_path = _p(new_xlsx)
        wb.save(new_path)
        if new_path != xlsx_path and os.path.exists(xlsx_path):
            os.remove(xlsx_path)
        print(f"Saved as {new_xlsx} (renamed from {current_xlsx})")

        new_src = elo_src.replace(f"'{current_xlsx}'", f"'{new_xlsx}'")
        with open(elo_py_path, 'w', encoding='utf-8') as f:
            f.write(new_src)
        print(f"Updated elo_engine.py: {current_xlsx} -> {new_xlsx}")
    else:
        wb.save(xlsx_path)
        print(f"Saved to {current_xlsx}")
else:
    wb.save(xlsx_path)
    print(f"Saved to {current_xlsx}")

# ── 4. Write JSON backup ──
cup_json = {
    'cup': cup_id,
    'cup_num': cup_num,
    'mapper': mapper,
    'players': [
        {'pos': position, 'name': name, 'time': time, 'round': rnd}
        for name, time, rnd, position in leaderboard
    ]
}
json_path = _p(f'cup_{cup_num}.json')
with open(json_path, 'w', encoding='utf-8') as f:
    json.dump(cup_json, f, ensure_ascii=False, indent=2)
print(f"JSON backup: cup_{cup_num}.json")
print()

# ── 5. Run elo_engine.py ──
print("=" * 50)
print("Running elo_engine.py...")
print("=" * 50)
result = subprocess.run([sys.executable, _p('elo_engine.py')], cwd=_dir)
if result.returncode != 0:
    print("ERROR: elo_engine.py failed!")
    sys.exit(1)
print()

# ── 6. Run build_cups.py ──
print("=" * 50)
print("Running build_cups.py...")
print("=" * 50)
result = subprocess.run([sys.executable, _p('build_cups.py')], cwd=_dir)
if result.returncode != 0:
    print("ERROR: build_cups.py failed!")
    sys.exit(1)
print()

# ── 7. Rebuild Cool Stats ──
cool_stats = [
    ('build_big3.py', 'Big 3 H2H'),
    ('build_giantkillers.py', 'Giant Killers'),
    ('build_consistency.py', 'Consistency Index'),
    ('elo_stability.py', 'ELO Stability'),
    ('build_fastest.py', 'Fastest Times'),
    ('build_whatif.py', 'What-If ELO'),
    ('build_altrank.py', 'Alt Rankings'),
]
print("=" * 50)
print("Rebuilding Cool Stats...")
print("=" * 50)
for script, label in cool_stats:
    path = _p(script)
    if os.path.exists(path):
        r = subprocess.run([sys.executable, path], cwd=_dir)
        if r.returncode != 0:
            print(f"  WARNING: {label} ({script}) failed!")
        else:
            print(f"  {label} OK")
    else:
        print(f"  SKIP: {script} not found")
print()

# ── 8. Refresh cross-comp ranking + SOF mod data ──
# Cross-comp pipeline: rebuilds allsofdata.json + allcompdata.json + the
# SOF mod's elo_pool.json (which now uses cross-comp ELO as its primary
# source, GTR rank regression as fallback). Replaces the old COTD-only
# join_cotd_gtr.py path.
print("=" * 50)
print("Refreshing cross-comp ranking + SOF data...")
print("=" * 50)
crosscomp_script = r"C:\Users\rafa\Desktop\Claude\zeepkist holistic\refresh.py"
sof_repo_pool = r"C:\Users\rafa\Desktop\Claude\zeepkist mod\Zeepkist-Strength-of-Field\elo_pool.json"

sof_ok = False
if os.path.exists(crosscomp_script):
    r = subprocess.run([sys.executable, crosscomp_script],
                       cwd=os.path.dirname(crosscomp_script))
    if r.returncode == 0:
        print(f"  Cross-comp + SOF elo_pool.json refreshed.")
        sof_ok = True
    else:
        print(f"  WARNING: cross-comp refresh failed (returncode={r.returncode}).")
        print(f"  Run manually: python \"{crosscomp_script}\"")
else:
    print(f"  SKIP: refresh script not found at {crosscomp_script}")
print()

# ── 9. Summary ──
print("=" * 50)
print(f"{cup_id} COMPLETE")
print(f"  Players: {len(leaderboard)}")
print(f"  Winner: {winner}")
if fastest_time:
    print(f"  Fastest: {fastest_time:.3f} by {fastest_name}")
print(f"  Columns: {col_start}-{col_start+3}")
if sof_ok:
    print(f"  SOF data: refreshed (commit+push the SOF repo too)")
print()
print("Next steps:")
print(f"  - Add map name to build_cups.py map_index")
print(f"  - Git commit + push (COTD repo) — REMEMBER to stage cup_{cup_num}.json (lexertools last-cup view fetches it)")
if sof_ok:
    print(f"  - Git commit + push (SOF repo: {sof_repo_pool})")
print("=" * 50)
