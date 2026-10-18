"""
new_cup.py — Automated cup processing from COTDTracker mod logs

Usage:
  python new_cup.py 153 "[RAW]MapperName" --map "Real Map Name"

Fully automatic: snapshot -> parse log -> results/ block + tracker log +
cup_N.json -> cup_meta.json (map/mapper/date for build_cups.py) -> all ELO
data -> localhost preview. results/ is the source of truth (results_store.py);
the xlsx backups are rebuilt from it by sync_xlsx.py on the PC.
Push stays manual: verify on http://localhost:8000 first.
Unattended runs: submissions_poll.py calls this with --log/--no-open for cups
submitted on submit.html; COTD_SKIP_EXTERNAL=1 skips the out-of-repo steps.
"""
import re, os, sys, json, subprocess, datetime, glob, shutil
# Cheap import: elo_engine only runs its pipeline as __main__. CANONICAL is
# read here for the alias-drift check.
from elo_engine import CANONICAL
import results_store
import external_steps
from cotd_parser import ParseError, cup_json_payload, fastest_round_label, parse_cup_log_file, time_to_ms
import cup_paths

# Force UTF-8 stdout so printing unicode aliases (e.g. the 𝒱V𝑜o𝒾i𝒹d𝒱 void name)
# in the alias-drift report can't crash the pipeline when stdout is redirected
# to a file (Windows defaults to cp1252, which can't encode those glyphs).
sys.stdout.reconfigure(encoding='utf-8')

_dir = os.path.dirname(os.path.abspath(__file__))
_p = lambda f: os.path.join(_dir, f)

LOG_PATH = r"C:\Program Files (x86)\Steam\steamapps\common\Zeepkist\BepInEx\LogOutput.log"
LIVE_LOG_PATH = r"C:\Program Files (x86)\Steam\steamapps\common\Zeepkist\BepInEx\LiveLeaderboardLogger.log"

# COTD_SKIP_EXTERNAL=1 skips the steps that write OUTSIDE this repo (cross-comp
# refresh, COTD SOF pool, raw-data backup). submissions_poll.py --rehearsal sets
# it so a run in a scratch copy cannot touch the real SOF repos or backup drive.
SKIP_EXTERNAL = os.environ.get('COTD_SKIP_EXTERNAL') == '1'

# ── Parse arguments ──
def _usage():
    print('Usage: python new_cup.py <cup_number> <mapper_name> --map "<map_name>"')
    print('                         [--exclude name1,name2,...] [--date YYYY-MM-DD]')
    print('                         [--log path] [--livelog path]')
    print('                         [--reprocess]   redo a cup that is already processed')
    print('                         [--no-open]     do not open the browser at the end')
    print('Example: python new_cup.py 153 "[MMM]Victor" --map "COTD - Blue Blitz"')
    print('Example: python new_cup.py 153 "PlusMicron" --map "Farewell" --exclude justMaki')
    sys.exit(1)

if len(sys.argv) < 3:
    _usage()

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
reprocess = '--reprocess' in sys.argv
no_open = '--no-open' in sys.argv

# Optional --log / --livelog overrides: process a cup from a saved log file
# (e.g. an attendee's LogOutput.log when you missed the cup) instead of the
# live BepInEx log. When --log is given without --livelog, the local live log
# is NOT used — it would be a stale, unrelated session — so the alias SID
# check is skipped rather than run against the wrong cup.
def _arg_after(flag):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None

def _resolve(p):
    return p if os.path.isabs(p) else os.path.join(_dir, p)

def _recycle(path):
    """Send a file to the Windows Recycle Bin — never permanently delete."""
    r = subprocess.run([
        'powershell', '-NoProfile', '-Command',
        'Add-Type -AssemblyName Microsoft.VisualBasic; '
        "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile("
        f"'{path}', 'OnlyErrorDialogs', 'SendToRecycleBin')"
    ], capture_output=True, text=True)
    return r.returncode == 0

def _load_cup_meta(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return json.load(f)

def _write_cup_meta(path, meta):
    """Atomic write (tmp + os.replace) so a crash never leaves a half file."""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
        f.write('\n')
    os.replace(tmp, path)

def restore_pre_cup_state(cup_num, cup_id):
    """Undo what the first run of cup N did to the source data so the normal
    flow can run again: send its results/ block to the Recycle Bin (a copy
    goes to backups/ first), put the book's name back, and drop the
    cup_meta.json entry. Only the newest block can be undone, because the
    next cup's column is placed after the last one."""
    path = os.path.join(_dir, results_store.RESULTS_DIR, 'cups', results_store.cup_slug(cup_id) + '.json')
    if not os.path.exists(path):
        print(f"ERROR: {os.path.relpath(path, _dir)} not found; nothing to undo.")
        sys.exit(1)
    blk = results_store.read_block(path)
    same_sheet = [b for b in results_store.blocks().values()
                  if b['book'] == blk['book'] and b['sheet'] == blk['sheet']]
    if blk['col'] != max(b['col'] for b in same_sheet):
        print(f"ERROR: {cup_id} is not the newest block in its sheet; undo the later cups first.")
        sys.exit(1)
    os.makedirs(_p('backups'), exist_ok=True)
    keep = _p(os.path.join('backups', f'{os.path.basename(path)}.pre_reprocess'))
    shutil.copy2(path, keep)
    if not _recycle(path):
        print(f"ERROR: could not send {os.path.basename(path)} to the Recycle Bin.")
        sys.exit(1)
    print(f"  {os.path.basename(path)} -> Recycle Bin (copy in backups/{os.path.basename(keep)})")
    books = results_store.books()
    book = next(b for b in books if b['id'] == blk['book'])
    m = re.fullmatch(r'COTD (\d+)-(\d+)\.xlsx', book['xlsx'])
    results_store.clear_cache()
    nums = [int(x.split()[1]) for x in results_store.cotd_ids() if re.fullmatch(r'COTD \d+', x)]
    if m and int(m.group(2)) == cup_num:
        book['xlsx'] = f"COTD {m.group(1)}-{max(n for n in nums if n < cup_num)}.xlsx"
        results_store.write_books(books)
        print(f"  books.json: {m.group(0)} -> {book['xlsx']}")
    meta_path_ = _p('cup_meta.json')
    meta = _load_cup_meta(meta_path_)
    if meta.pop(cup_id, None) is not None:
        _write_cup_meta(meta_path_, meta)
        print(f"  removed {cup_id} from cup_meta.json")

# Required --map: the real map name, written to cup_meta.json so build_cups.py
# needs no hand-edit (map_index / CUP_DATES additions are dead — see cup_meta).
map_name = _arg_after('--map')
if not map_name:
    print("ERROR: --map \"<map_name>\" is required (goes to cup_meta.json).")
    _usage()

# Optional --date YYYY-MM-DD override. Without it the cup date is derived from
# the log file's mtime; a log written before 06:00 counts as the PREVIOUS day
# (cups run Saturday evening and often end past midnight — COTD 148 gotcha).
_date_override = _arg_after('--date')
if _date_override and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', _date_override):
    print(f"ERROR: --date must be YYYY-MM-DD, got {_date_override!r}")
    sys.exit(1)

_log_override = _arg_after('--log')
_livelog_override = _arg_after('--livelog')
if _log_override:
    LOG_PATH = _resolve(_log_override)
    LIVE_LOG_PATH = _resolve(_livelog_override) if _livelog_override else None
    print(f"Log override: {LOG_PATH}")
    print(f"Livelog override: {LIVE_LOG_PATH if LIVE_LOG_PATH else '(none — alias SID check skipped)'}")
elif _livelog_override:
    LIVE_LOG_PATH = _resolve(_livelog_override)

print(f"Processing {cup_id}, mapper: {mapper}, map: {map_name}")
if extra_excluded:
    print(f"Also excluding: {', '.join(extra_excluded)}")
print()

# ── 0a. Idempotency gate ──
# Refuse to process a cup that's already in results/ or cup_meta.json: a
# re-run would add a DUPLICATE block and corrupt every downstream build.
if reprocess:
    if cup_id not in results_store.cotd_ids() and cup_id not in _load_cup_meta(_p('cup_meta.json')):
        print(f"ERROR: --reprocess given but {cup_id} is not processed "
              f"(not in results/ or cup_meta.json); drop the flag.")
        sys.exit(1)
    print("=" * 50)
    print(f"--reprocess: restoring the state from before {cup_id}")
    print("=" * 50)
    restore_pre_cup_state(cup_num, cup_id)
    print()

meta_path = _p('cup_meta.json')
cup_meta = _load_cup_meta(meta_path)
existing_cup_ids = results_store.cotd_ids()
if cup_id in existing_cup_ids or cup_id in cup_meta:
    where = []
    if cup_id in existing_cup_ids:
        where.append('results/')
    if cup_id in cup_meta:
        where.append('cup_meta.json')
    print(f"ERROR: {cup_id} is already processed (found in {' + '.join(where)}).")
    print(f"  Re-run with --reprocess to undo it and redo it, or check the cup number.")
    sys.exit(1)

# ── 0b. Snapshot previous standings (was a separate manual step) ──
# Explicit target = previous cup, so a partial re-run can never snapshot the
# post-update standings by accident. snapshot.py backs up the old snapshot
# itself and fails loud if alldata.json is half-written.
print("=" * 50)
print(f"Running snapshot.py {cup_num - 1}...")
print("=" * 50)
r = subprocess.run([sys.executable, _p('snapshot.py'), str(cup_num - 1)], cwd=_dir)
if r.returncode != 0:
    print("ERROR: snapshot.py failed — fix alldata.json before processing the cup.")
    sys.exit(1)
print()

# ── 1. Save raw log + parse mod logs ──
log_dir = _p('cup logs')
os.makedirs(log_dir, exist_ok=True)
import shutil
log_backup = os.path.join(log_dir, f'cotd_{cup_num}.log')
if os.path.abspath(LOG_PATH) != os.path.abspath(log_backup):
    shutil.copy2(LOG_PATH, log_backup)
    print(f"Raw log saved: {log_backup}")
else:
    print(f"Raw log already in place: {log_backup}")
live_log_backup = os.path.join(log_dir, f'cotd_{cup_num}_liveleaderboard.log')
if LIVE_LOG_PATH and os.path.exists(LIVE_LOG_PATH):
    if os.path.abspath(LIVE_LOG_PATH) != os.path.abspath(live_log_backup):
        shutil.copy2(LIVE_LOG_PATH, live_log_backup)
        print(f"Live log saved: {live_log_backup}")
    else:
        print(f"Live log already in place: {live_log_backup}")
else:
    print(f"⚠ Live log not found at {LIVE_LOG_PATH} — alias SID check will be skipped")
    live_log_backup = None

try:
    parsed = parse_cup_log_file(LOG_PATH, excluded)
except ParseError as exc:
    print(f"ERROR: {exc}")
    sys.exit(1)

# Excluded names that never appear in the log did not exclude anyone: either
# they genuinely didn't play, or the raw name is wrong (COTD 152: mapper passed
# as "Victor" while the log had "[MMM]Victor" — he got counted as a player).
for _w in parsed.warnings:
    print(f"⚠ WARNING: {_w}")

if not parsed.candidates:
    print("ERROR: Could not determine winner.")
    sys.exit(1)
if parsed.ambiguous:
    # "Named but never eliminated" resolved to 2+ players — usually a
    # mid-cup disconnect the tracker never eliminated, or a truncated log.
    # An unattended run must not guess; add the non-winner(s) to --exclude
    # or fix the log and re-run.
    print(f"ERROR: winner is ambiguous — {len(parsed.candidates)} players were never eliminated:")
    for n in parsed.candidates:
        print(f"  - {n!r}")
    print("Pick the real winner from the VOD/log; re-run with the others handled")
    print("(e.g. --exclude for non-players, or use a more complete log).")
    sys.exit(1)

winner = parsed.winner
winner_time = parsed.winner_time_raw
# (name, time, round, position) tuples: the shape the results/JSON writers below
# have always consumed.
leaderboard = [(p.name, p.time_raw, p.round, p.pos) for p in parsed.leaderboard]
fastest_time, fastest_name, fastest_round = parsed.fastest_time, parsed.fastest_name, parsed.fastest_round

print(f"Parsed {len(leaderboard)} players (excluded: {', '.join(sorted(excluded))})")
print(f"Winner: {winner} ({winner_time})")
print(f"Rounds in log: {parsed.n_rounds}")
print()

# ── 1b. Cross-check leaderboard names against livelog Steam IDs ──
# Catches alias drift: a player who joins a new clan and ends up tracked as a
# fresh identity (e.g. "[NewB]Zeus" → "[SLOW]Zeus" → "Zeus"). Same Steam ID =
# same player; mismatches between the lobby name and the canonical name in
# steam_ids.json get flagged with a copy-pasteable CANONICAL entry suggestion.
def check_aliases_against_livelog(leaderboard, live_log_path, steam_ids_path,
                                  report_path=None):
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
    # alias -> canonical from elo_engine.CANONICAL (imported at the top)
    canon_dict = CANONICAL
    alias_to_canon, canon_names = {}, set(canon_dict.keys())
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
    # Build the report as lines: printed to console AND written to a file so
    # an unattended run's findings aren't lost when the console closes. The
    # report never blocks the pipeline — until CANONICAL/steam_ids.json are
    # curated, the player is simply tracked under their raw name.
    out = []
    out.append("=" * 50)
    out.append("ALIAS CHECK — livelog SIDs vs steam_ids.json")
    out.append("=" * 50)
    if drifts:
        out.append(f"\n{len(drifts)} alias drift(s):")
        for name, sid, canon in drifts:
            out.append(f"  - {name!r} (sid {sid}) should map to canonical {canon!r}")
        out.append("\nUpdate CANONICAL in elo_engine.py — append these to the matching entry:")
        from collections import defaultdict
        by_canon = defaultdict(list)
        for name, _, canon in drifts:
            by_canon[canon].append(name)
        for canon, names in by_canon.items():
            names_lit = ', '.join(repr(n) for n in sorted(set(names)))
            out.append(f"  '{canon}': [..., {names_lit}],")
    if new_players:
        out.append(f"\n{len(new_players)} new player(s) — no entry in steam_ids.json:")
        for name, sid in new_players:
            out.append(f"  - {name!r} (sid {sid})")
        out.append("\nIf any are returning under a new name, add to steam_ids.json:")
        for name, sid in new_players:
            out.append(f'  "{name}": "{sid}",')
    print()
    print('\n'.join(out))
    print()
    if report_path:
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(out) + '\n')
        print(f"Alias report saved: {os.path.relpath(report_path, _dir)}")

check_aliases_against_livelog(
    leaderboard,
    live_log_backup,
    _p('steam_ids.json'),
    report_path=_p(os.path.join('cup logs', f'cotd_{cup_num}_alias_report.txt')),
)

# ── 3. Write the results/ block and the tracker log ──
# Same cells new_cup.py always wrote into the workbook; sync_xlsx.py copies
# them into the xlsx backup later. Elim Time is integer milliseconds (or
# 'DNF'), from the same helper as cup_N.json, so the two can never disagree.
fastest_line = (f'Fastest Time: {fastest_time:.3f} by {fastest_name} in {fastest_round_label(parsed)}'
                if fastest_time is not None else None)
block_path = results_store.add_cup_block(
    cup_id, f'Map: {map_name} by {mapper}', fastest_line,
    [[position, name, time_to_ms(time), rnd] for name, time, rnd, position in leaderboard])
print(f"results: {os.path.relpath(block_path, _dir)}")

tracker_path = cup_paths.tracker_log_path(cup_num, _dir)
with open(LOG_PATH, encoding='utf-8', errors='replace') as f:
    _tracker_lines = [l for l in f.readlines() if 'COTDTracker' in l]
with open(tracker_path, 'w', encoding='utf-8', newline='') as f:
    f.writelines(_tracker_lines)
print(f"tracker log: {os.path.relpath(tracker_path, _dir)} ({len(_tracker_lines)} lines)")

# ── 4. Write JSON backup ──
cup_json = cup_json_payload(parsed, cup_num, mapper)
cup_paths.ensure_dirs(_dir)
json_path = cup_paths.cup_json_path(cup_num, _dir)
with open(json_path, 'w', encoding='utf-8') as f:
    json.dump(cup_json, f, ensure_ascii=False, indent=2)
print(f"JSON backup: {os.path.relpath(json_path, _dir)}")
print()

# ── 4b. Write cup_meta.json (map/mapper/date for build_cups.py) ──
# Replaces the manual map_index + CUP_DATES edits in build_cups.py source.
# Date: --date override, else the log's mtime — but a log written before
# 06:00 belongs to the PREVIOUS day (cups end past midnight; COTD 148's log
# was stamped early Sunday 06-14 for the Saturday 06-13 cup).
if _date_override:
    cup_date = _date_override
else:
    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(LOG_PATH))
    d = mtime.date()
    if mtime.hour < 6:
        d -= datetime.timedelta(days=1)
    cup_date = d.isoformat()

cup_meta[cup_id] = {'map': map_name, 'mapper': mapper, 'date': cup_date}
_write_cup_meta(meta_path, cup_meta)
print(f"cup_meta.json: {cup_id} = {map_name!r} by {mapper!r}, {cup_date}")
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
# build_altrank.py is NOT just a cool stat: it's the second writer of
# alldata.json (elo_engine.py overwrites the file with 5 keys, build_altrank
# re-appends standard/trueskill/cupDates). If it fails, alldata.json stays
# half-written, altrank.html breaks and the next snapshot.py run crashes —
# this shipped to the live site once (2026-06-02) and blanked the leaderboard.
# So its failure aborts the pipeline; the rest only warn.
cool_stats = [
    ('build_big3.py', 'Big 3 H2H'),
    ('build_giantkillers.py', 'Giant Killers'),
    ('build_consistency.py', 'Consistency Index'),
    ('elo_stability.py', 'ELO Stability'),
    ('build_fastest.py', 'Fastest Times'),
    ('build_whatif.py', 'What-If ELO'),
    ('build_streaks.py', 'Streak Records'),
    ('build_rounds.py', 'Clean Sweeps'),
    ('build_altrank.py', 'Alt Rankings'),
]
FATAL_STATS = {'build_altrank.py'}
failed_steps = []
print("=" * 50)
print("Rebuilding Cool Stats...")
print("=" * 50)
for script, label in cool_stats:
    path = _p(script)
    if os.path.exists(path):
        r = subprocess.run([sys.executable, path], cwd=_dir)
        if r.returncode != 0:
            if script in FATAL_STATS:
                print(f"ERROR: {label} ({script}) failed — alldata.json is "
                      f"HALF-WRITTEN (missing standard/trueskill/cupDates).")
                print(f"Fix the error and re-run: python {script}")
                print("Do NOT push until it succeeds.")
                sys.exit(1)
            failed_steps.append(f"{label} ({script})")
            print(f"  WARNING: {label} ({script}) failed!")
        else:
            print(f"  {label} OK")
    else:
        if script in FATAL_STATS:
            print(f"ERROR: {script} not found — alldata.json would stay half-written.")
            sys.exit(1)
        failed_steps.append(f"{label} ({script}) — not found")
        print(f"  SKIP: {script} not found")
print()

# ── 8. Cross-comp ranking + SOF pools (other repos on this PC) ──
# external_steps.py; catch_up.py runs the same steps after an online cup.
if SKIP_EXTERNAL:
    print("  SKIP (COTD_SKIP_EXTERNAL): cross-comp refresh")
    print("  SKIP (COTD_SKIP_EXTERNAL): COTD SOF pool")
    sof_ok = cotd_pool_ok = False
else:
    sof_ok = external_steps.refresh_crosscomp()
    cotd_pool_ok = external_steps.refresh_cotd_pool()
print()

# ── 9. Summary ──
print("=" * 50)
print(f"{cup_id} COMPLETE")
if failed_steps:
    print(f"  !! {len(failed_steps)} non-fatal step(s) FAILED — fix before pushing:")
    for s in failed_steps:
        print(f"     - {s}")
print(f"  Players: {len(leaderboard)}")
print(f"  Winner: {winner}")
if fastest_time:
    print(f"  Fastest: {fastest_time:.3f} by {fastest_name}")
print(f"  Results: {os.path.relpath(block_path, _dir)}")
if sof_ok or cotd_pool_ok:
    print(f"  SOF data: refreshed (commit+push the SOF repo too)")
print()
print("Next steps (after verifying on localhost):")
print(f"  - Git commit + push (COTD repo) — REMEMBER to stage cup_meta.json AND cup_data/cup_{cup_num}.json (lexertools last-cup view fetches it)")
external_steps.sof_push_reminder(sof_ok, cotd_pool_ok)
print("=" * 50)

# ── 9b. Mirror the gitignored files off-drive ──
if SKIP_EXTERNAL:
    print("  SKIP (COTD_SKIP_EXTERNAL): raw-data backup")
    print()
else:
    external_steps.backup_raw_data()

# ── 10. Localhost preview ──
# The run ends with the updated site visible on localhost:8000 (COTD's
# reserved port) — verify there BEFORE pushing. If nothing is listening,
# start a detached static server that outlives this script.
import socket
_serving = False
try:
    with socket.create_connection(('127.0.0.1', 8000), timeout=0.3):
        _serving = True
except OSError:
    pass
if _serving:
    print("localhost:8000 already serving — updated data is live there.")
else:
    _flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([sys.executable, '-m', 'http.server', '8000'],
                     cwd=_dir, creationflags=_flags,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("Started http.server on localhost:8000 (detached).")
if no_open:
    print("--no-open: browser not opened. Verify on http://localhost:8000, then push manually.")
else:
    try:
        os.startfile('http://localhost:8000')
        print("Opened http://localhost:8000 — verify the cup, then push manually.")
    except OSError:
        print("Open http://localhost:8000 to verify the cup, then push manually.")
