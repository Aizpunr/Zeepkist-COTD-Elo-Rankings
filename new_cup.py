"""
new_cup.py — Automated cup processing from COTDTracker mod logs

Usage:
  python new_cup.py 135 "MapperName"

Parses mod logs, writes to xlsx + JSON backup, rebuilds all ELO data.
"""
import re, os, sys, json, subprocess
import openpyxl

_dir = os.path.dirname(os.path.abspath(__file__))
_p = lambda f: os.path.join(_dir, f)

LOG_PATH = r"C:\Program Files (x86)\Steam\steamapps\common\Zeepkist\BepInEx\LogOutput.log"
COLS_PER_CUP = 6  # 4 data columns + 2 blank spacer

# ── Parse arguments ──
if len(sys.argv) < 3:
    print("Usage: python new_cup.py <cup_number> <mapper_name>")
    print('Example: python new_cup.py 135 "[20x]K410K3N"')
    sys.exit(1)

cup_num = int(sys.argv[1])
mapper = sys.argv[2]
cup_id = f"COTD {cup_num}"

print(f"Processing {cup_id}, mapper: {mapper}")
print()

# ── 1. Save raw log + parse mod logs ──
log_dir = _p('cup logs')
os.makedirs(log_dir, exist_ok=True)
import shutil
log_backup = os.path.join(log_dir, f'cotd_{cup_num}.log')
shutil.copy2(LOG_PATH, log_backup)
print(f"Raw log saved: {log_backup}")

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
# Track last known time per player across rounds (for DNF elim display)
last_known_time = {}
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
            if time_str != 'DNF':
                last_known_time[name] = time_str
        m2 = re.search(r'Eliminating (?:DNF|on time): (.+)', line)
        if m2:
            name = m2.group(1).strip()
            if name not in eliminated_names:
                eliminated_names.append(name)
    # Only count rounds with eliminations (skip discovery)
    if not eliminated_names:
        continue
    actual_round += 1
    for name in eliminated_names:
        if name != mapper:
            # Use current round time, fall back to last known time
            time = player_times.get(name, 'DNF')
            if time == 'DNF':
                time = last_known_time.get(name, 'DNF')
            elim_order.append((name, time, actual_round))

# Find winner
all_named = set()
for rnd in rounds:
    for line in rnd:
        m = re.search(r'Player (.+?): Time:', line)
        if m:
            all_named.add(m.group(1).strip())
elim_set = {e[0] for e in elim_order}
winners = [n for n in all_named if n not in elim_set and n != mapper]
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

# Build leaderboard with tied positions for same-round eliminations
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
    for name, time, r in group:
        leaderboard.append((name, time, r, pos))
    pos += len(group)

print(f"Parsed {len(leaderboard)} players (mapper {mapper} excluded)")
print(f"Winner: {winner} ({winner_time})")
print(f"Rounds in log: {len(rounds)}")
print()

# Find fastest time
fastest_time = None
fastest_name = None
fastest_round = None
for rnd_num, rnd in enumerate(rounds, 1):
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

# ── 2. Auto-detect xlsx file + columns ──
elo_py_path = _p('elo_engine.py')
with open(elo_py_path) as f:
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
        with open(elo_py_path, 'w') as f:
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

# ── 8. Summary ──
print("=" * 50)
print(f"{cup_id} COMPLETE")
print(f"  Players: {len(leaderboard)}")
print(f"  Winner: {winner}")
if fastest_time:
    print(f"  Fastest: {fastest_time:.3f} by {fastest_name}")
print(f"  Columns: {col_start}-{col_start+3}")
print()
print("Next steps:")
print(f"  - Add map name to build_cups.py map_index")
print(f"  - Git commit + push")
print("=" * 50)
