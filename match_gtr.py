"""Match active GTR players (rank > 0) against the COTD roster.

Read-only. Walks gtr_userpoints.json through the existing NAME_MAP
(alldata.json names + CANONICAL aliases + tag-stripping) and reports:
- how many GTR-active players resolve to a COTD canonical
- how many qualified COTD missing-steamID players a merge would fill
- conflicts: any canonical claimed by both a TyO/livelog steamID and a
  different GTR steamID

No files are modified.

Run: python match_gtr.py
"""
import json, os, re, sys, io
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
GTR_PATH = os.path.join(HERE, 'gtr_userpoints.json')
ALLDATA = os.path.join(HERE, 'alldata.json')
SEED_PATH = os.path.join(HERE, 'steam_ids.json')

# Quiet import of CANONICAL (elo_engine has no __main__ guard)
_real = sys.stdout
sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding='utf-8', write_through=True)
try:
    from elo_engine import CANONICAL  # type: ignore
finally:
    sys.stdout = _real

NAME_MAP = {}
for canonical, aliases in CANONICAL.items():
    NAME_MAP[canonical] = canonical
    for a in aliases:
        NAME_MAP[a] = canonical

with open(ALLDATA, encoding='utf-8') as f:
    alldata = json.load(f)
for p in alldata['weighted']:
    NAME_MAP.setdefault(p['n'], p['n'])

# Case-insensitive fallback map (last-write-wins, fine for our scale)
NAME_MAP_LOWER = {k.lower(): v for k, v in NAME_MAP.items()}


def strip_tag(name):
    return re.sub(r'\[.*?\]\s*', '', name).strip()


def resolve(name):
    if name in NAME_MAP:
        return NAME_MAP[name], 'exact'
    s = strip_tag(name)
    if s and s in NAME_MAP:
        return NAME_MAP[s], 'tag-stripped'
    if name.lower() in NAME_MAP_LOWER:
        return NAME_MAP_LOWER[name.lower()], 'case-insensitive'
    if s and s.lower() in NAME_MAP_LOWER:
        return NAME_MAP_LOWER[s.lower()], 'case+tag'
    return None, None


def main():
    gtr = json.load(open(GTR_PATH, encoding='utf-8'))
    active = [n for n in gtr if n['rank'] > 0]
    print(f'GTR userPoints: {len(gtr)} total nodes, {len(active)} active (rank > 0)')

    seed = {}
    if os.path.exists(SEED_PATH):
        seed = json.load(open(SEED_PATH, encoding='utf-8'))
    print(f'Existing steam_ids.json: {len(seed)} entries')

    # Resolve each active GTR node
    matched = []        # (rank, points, sid, gtr_name, canonical, mode)
    unmatched = []      # (rank, points, sid, gtr_name)
    by_canonical = defaultdict(list)   # canonical -> [(sid, gtr_name, ...)]
    for n in active:
        c, mode = resolve(n['steamName'])
        if c is None:
            unmatched.append((n['rank'], n['points'], n['steamId'], n['steamName']))
        else:
            matched.append((n['rank'], n['points'], n['steamId'], n['steamName'], c, mode))
            by_canonical[c].append((n['steamId'], n['steamName'], mode))

    print(f'\nResolved {len(matched)}/{len(active)} active GTR players to a COTD canonical')
    by_mode = defaultdict(int)
    for *_, mode in matched:
        by_mode[mode] += 1
    for k, v in sorted(by_mode.items()):
        print(f'  via {k:<18} {v}')

    # Conflicts: canonical resolved to multiple distinct steamIDs (would mean
    # we have wrong aliases or the same display name covers two real people)
    conflicts = {c: hits for c, hits in by_canonical.items() if len({h[0] for h in hits}) > 1}
    if conflicts:
        print(f'\n[!] {len(conflicts)} canonicals matched by multiple GTR steamIDs:')
        for c, hits in sorted(conflicts.items()):
            print(f'  {c}: {hits}')

    # Cross-check against existing seed: do the GTR matches agree?
    disagreements = []
    new_fills = []
    confirmed = []
    for rank, pts, sid, gtr_name, c, mode in matched:
        if c in seed:
            if seed[c] == sid:
                confirmed.append(c)
            else:
                disagreements.append((c, seed[c], sid, gtr_name, mode))
        else:
            new_fills.append((rank, pts, sid, gtr_name, c, mode))

    print(f'\nCross-check vs steam_ids.json:')
    print(f'  confirmed (GTR agrees with our seed): {len(confirmed)}')
    print(f'  new fills (GTR adds a steamID we did not have): {len(new_fills)}')
    print(f'  disagreements (GTR steamID != seeded steamID): {len(disagreements)}')
    if disagreements:
        print('  --- disagreements ---')
        for c, seeded, gtr_sid, gtr_name, mode in disagreements:
            print(f'    {c}: seed={seeded}  gtr={gtr_sid} ({gtr_name}, via {mode})')

    # Coverage of qualified COTD players
    by_name = {p['n']: p for p in alldata['weighted']}
    qualified = {p['n'] for p in alldata['weighted']
                 if p['c'] >= 5 or (p.get('g', 0) + p.get('s', 0) + p.get('z', 0)) > 0}
    have_seed = qualified & set(seed.keys())
    have_after_merge = qualified & (set(seed.keys()) | {c for *_, c, _ in matched})
    print(f'\nQualified COTD players: {len(qualified)}')
    print(f'  current coverage from seed:           {len(have_seed)} ({len(have_seed)*100//max(1,len(qualified))}%)')
    print(f'  coverage after GTR merge would be:    {len(have_after_merge)} ({len(have_after_merge)*100//max(1,len(qualified))}%)')

    still_missing = sorted(qualified - have_after_merge,
                            key=lambda n: -by_name[n]['c'])
    print(f'\nQualified players still missing AFTER GTR merge: {len(still_missing)}')
    for n in still_missing[:20]:
        p = by_name[n]
        print(f'  {p["c"]:>3} cups, podiums={p["g"]}/{p["s"]}/{p["z"]:<3}  {n}')

    # Top GTR players who do NOT match any COTD canonical (pure grinders)
    print(f'\nTop 20 unmatched active GTR players (no COTD presence):')
    for rank, pts, sid, gtr_name in sorted(unmatched, key=lambda x: x[0])[:20]:
        print(f'  #{rank:>3}  pts={pts:>6}  {sid}  {gtr_name}')


if __name__ == '__main__':
    main()
