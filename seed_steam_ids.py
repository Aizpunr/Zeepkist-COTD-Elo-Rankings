"""Seed steam_ids.json from TyO JSON logs (Phase 1 of name -> steamID transition).

Reads every C:/Users/rafa/Desktop/Claude/TyO/logs/*.json, collects every
(steamID, username) pair seen, resolves each steamID to a COTD canonical name
via elo_engine.CANONICAL, and writes a {canonical_name: "76561..."} map.

Prints a coverage report:
- how many unique steamIDs we found
- how many resolved cleanly to a canonical
- which observed accounts didn't match any canonical (probably new players or
  aliases we never registered)
- which qualified COTD players (cups>=5 OR any podium) still have no steamID

Run: python seed_steam_ids.py
"""
import json, os, re, sys, io
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
CLAUDE_DIR = os.path.dirname(HERE)
TYO_LOGS = os.path.join(CLAUDE_DIR, 'TyO', 'logs')
ALLDATA = os.path.join(HERE, 'alldata.json')
OUT_JSON = os.path.join(HERE, 'steam_ids.json')

# All known LiveLeaderboardLogger log files. The deployed log under BepInEx
# accumulates across sessions; the petite_*_liveleaderboard.log copies are
# snapshots of that file taken after each cup. Reading all of them is safe —
# the obs collector dedupes on (steamID, username) frequency.
LIVELOG_FILES = [
    os.path.join(CLAUDE_DIR, 'petite cup stats', 'cup logs', 'petite_43_liveleaderboard.log'),
    os.path.join(CLAUDE_DIR, 'petite cup stats', 'cup logs', 'petite_44_liveleaderboard.log'),
    r'C:\Program Files (x86)\Steam\steamapps\common\Zeepkist\BepInEx\LiveLeaderboardLogger.log',
]

# Import CANONICAL without running elo_engine's full pipeline output.
# elo_engine has no __main__ guard and reconfigures stdout, so we redirect.
_real_stdout = sys.stdout
sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding='utf-8', write_through=True)
try:
    from elo_engine import CANONICAL  # type: ignore
finally:
    sys.stdout = _real_stdout

# alias -> canonical, plus canonical -> canonical (identity)
NAME_MAP = {}
for canonical, aliases in CANONICAL.items():
    NAME_MAP[canonical] = canonical
    for a in aliases:
        NAME_MAP[a] = canonical

# CANONICAL only lists players who needed alias merging. Most COTD players
# never had spelling variants and are absent from CANONICAL but present in
# alldata.json. Treat every alldata player name as its own canonical so the
# steamID resolver can match them too.
with open(ALLDATA, encoding='utf-8') as _f:
    _alldata = json.load(_f)
for _p in _alldata['weighted']:
    NAME_MAP.setdefault(_p['n'], _p['n'])


def strip_tag(name):
    return re.sub(r'\[.*?\]\s*', '', name).strip()


def resolve_canonical(observed_names):
    """Return canonical name (str) or None if no observed name maps."""
    for n in observed_names:
        if n in NAME_MAP:
            return NAME_MAP[n]
        s = strip_tag(n)
        if s and s in NAME_MAP:
            return NAME_MAP[s]
    return None


# RESULT|<round>|<sid>|<name>|... — v0.2.0 LiveLeaderboardLogger format
RESULT_RE = re.compile(r'RESULT\|\d+\|(\d+)\|([^|]+)\|')


def collect_from_tyo(obs):
    log_files = sorted(f for f in os.listdir(TYO_LOGS) if f.endswith('.json'))
    rows = 0
    for fname in log_files:
        path = os.path.join(TYO_LOGS, fname)
        with open(path, encoding='utf-8-sig') as f:
            data = json.load(f)
        for rnd in data.get('rounds', []):
            for pr in rnd.get('playerResults', []):
                sid = pr.get('steamID')
                un = pr.get('username') or ''
                if sid is None or not un:
                    continue
                obs[str(sid)][un] += 1
                rows += 1
                for k_sid, k_un in (
                    ('targetSteamID', 'targetUsername'),
                    ('targetedBySteamID', 'targetedByUsername'),
                ):
                    other_sid = pr.get(k_sid)
                    other_un = pr.get(k_un) or ''
                    if other_sid and other_un:
                        obs[str(other_sid)][other_un] += 1
                        rows += 1
    print(f'  TyO logs: {len(log_files)} files, {rows} (sid,name) rows')


def collect_from_livelog(obs):
    files_read = 0
    rows = 0
    for path in LIVELOG_FILES:
        if not os.path.exists(path):
            continue
        files_read += 1
        with open(path, encoding='utf-8-sig', errors='replace') as f:
            for line in f:
                m = RESULT_RE.search(line)
                if not m:
                    continue
                sid, un = m.group(1), m.group(2).strip()
                if not un:
                    continue
                obs[sid][un] += 1
                rows += 1
    print(f'  LiveLeaderboardLogger: {files_read} files, {rows} RESULT rows')


def collect_observations():
    """{steamID_str: Counter(username)} across every known data source."""
    obs = defaultdict(Counter)
    collect_from_tyo(obs)
    collect_from_livelog(obs)
    return obs


def main():
    obs = collect_observations()
    print(f'Unique steamIDs observed across TyO logs: {len(obs)}')

    # Resolve each steamID to a canonical via observed usernames (most freq first)
    sid_to_canonical = {}  # steamID -> canonical
    canonical_to_sid = defaultdict(list)  # canonical -> [steamID, ...]
    unresolved = []  # (steamID, [observed_names_by_freq])

    for sid, name_counter in obs.items():
        ordered = [n for n, _ in name_counter.most_common()]
        c = resolve_canonical(ordered)
        if c is None:
            unresolved.append((sid, ordered))
        else:
            sid_to_canonical[sid] = c
            canonical_to_sid[c].append(sid)

    print(f'  resolved to a known canonical: {len(sid_to_canonical)}')
    print(f'  unresolved (no NAME_MAP match): {len(unresolved)}')

    # Conflict detection — same canonical claimed by multiple steamIDs
    conflicts = {c: sids for c, sids in canonical_to_sid.items() if len(sids) > 1}
    if conflicts:
        print(f'\n[!] Conflicts ({len(conflicts)} canonicals claimed by multiple steamIDs):')
        for c, sids in sorted(conflicts.items()):
            print(f'  {c}: {sids}')
            for sid in sids:
                top = obs[sid].most_common(3)
                print(f'    {sid} -> seen as {top}')

    # Write JSON — pick the steamID with the most observations on conflict
    out = {}
    for c, sids in canonical_to_sid.items():
        if len(sids) == 1:
            out[c] = sids[0]
        else:
            sids_sorted = sorted(sids, key=lambda s: -sum(obs[s].values()))
            out[c] = sids_sorted[0]

    out_sorted = dict(sorted(out.items(), key=lambda kv: kv[0].lower()))
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(out_sorted, f, ensure_ascii=False, indent=2)
    print(f'\nWrote {OUT_JSON} with {len(out_sorted)} canonical -> steamID entries.')

    # Coverage vs qualified COTD roster (cups >= 5 OR any podium)
    with open(ALLDATA, encoding='utf-8') as f:
        alldata = json.load(f)
    qualified = []
    for p in alldata['weighted']:
        if p['c'] >= 5 or (p.get('g', 0) + p.get('s', 0) + p.get('z', 0)) > 0:
            qualified.append(p['n'])
    qualified_set = set(qualified)
    have = qualified_set & set(out.keys())
    miss = qualified_set - set(out.keys())
    print(f'\nQualified COTD players (cups>=5 OR any podium): {len(qualified_set)}')
    print(f'  with steamID: {len(have)} ({len(have)*100//max(1,len(qualified_set))}%)')
    print(f'  missing steamID: {len(miss)}')

    # Sort missing by 'rank usefulness' — players with most cups first
    by_name = {p['n']: p for p in alldata['weighted']}
    miss_sorted = sorted(miss, key=lambda n: -by_name[n]['c'])
    print('\nTop 30 qualified players still missing a steamID (by cups played):')
    for n in miss_sorted[:30]:
        p = by_name[n]
        print(f'  {p["c"]:>3} cups, podiums={p["g"]}/{p["s"]}/{p["z"]:<3}  {n}')

    # Unresolved observed accounts -> these are TyO players who don't appear in COTD
    # CANONICAL at all. Could be new players, or aliases we never logged.
    if unresolved:
        print(f'\n{len(unresolved)} unresolved steamIDs (TyO players not in COTD CANONICAL):')
        unresolved_sorted = sorted(unresolved, key=lambda x: -sum(obs[x[0]].values()))
        for sid, names in unresolved_sorted[:30]:
            top = obs[sid].most_common(3)
            print(f'  {sid}  {top}')


if __name__ == '__main__':
    main()
