"""Merge active GTR players into steam_ids.json.

Walks gtr_userpoints.json (active only), resolves each steamName through
NAME_MAP, and writes any new (canonical -> steamId) pair into steam_ids.json.
Existing entries are NOT overwritten — TyO/livelog observations rank higher
than GTR's name-based join.

Skip list: canonicals where multiple GTR steamIDs claim the same name.
Those need manual disambiguation. Run match_gtr.py to see the conflicts.

Run: python merge_gtr.py
"""
import json, os, re, sys, io
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
GTR_PATH = os.path.join(HERE, 'gtr_userpoints.json')
ALLDATA = os.path.join(HERE, 'alldata.json')
SEED_PATH = os.path.join(HERE, 'steam_ids.json')

# Canonicals flagged for manual review — multiple GTR steamIDs claim them.
# Add or remove as the situation gets resolved. Naomi was resolved (Naomi :3
# is the same player and is now an alias in CANONICAL).
SKIP_CANONICALS = set()

# Pre-resolved manual overrides for canonicals where GTR has multiple
# steamIDs with the same display name. Wins over GTR auto-resolution.
#
# Hydro: GTR rank #10 account is the real Hydro (115k pts). The other GTR
# 'l3purple' account (76561199643465013) is a separate newer player who
# only shares a name old-Hydro used once in COTD 43.
#
# Pants: two different real-life-related accounts (likely brothers per
# aizpun) share the in-game name "Pants" indistinguishably. Both top-50
# grinders, both ~100k pts. Originally picked the higher GTR rank
# (#29: 76561199529259554) by convention. Flipped 2026-05-04 after COTD 142
# livelog directly observed the OTHER account (#43: 76561199498272376) racing
# as Pants and finishing pos 8 — so the cup-playing brother is the rank-#43
# account, not the rank-#29 one. THE Pants in our data is now #43.
# If the rank-#29 account (76561199529259554) ever shows up in a livelog'd
# cup, treat as a separate new canonical — don't try to retroactively split
# the 25+ historical Pants entries.
MANUAL_OVERRIDES = {
    'Hydro': '76561199027567424',
    'Pants': '76561199498272376',
}


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

# Some alldata canonicals carry a clan tag baked into the name itself
# (e.g. "[ZET]Sword125", "[oops] Wombat!"). When GTR has them under the
# bare name ("Sword125", "Wombat!"), we want to match. Build a reverse
# strip index — but only for unambiguous cases (one canonical strips to
# this bare name).
def _strip_tag(name):
    import re as _re
    return _re.sub(r'\[.*?\]\s*', '', name).strip()

_strip_groups = {}
for canonical in list(NAME_MAP.keys()):
    s = _strip_tag(canonical)
    if s and s != canonical:
        _strip_groups.setdefault(s, set()).add(NAME_MAP[canonical])
for bare, canonicals in _strip_groups.items():
    if len(canonicals) == 1 and bare not in NAME_MAP:
        NAME_MAP[bare] = next(iter(canonicals))

NAME_MAP_LOWER = {k.lower(): v for k, v in NAME_MAP.items()}


def strip_tag(name):
    return re.sub(r'\[.*?\]\s*', '', name).strip()


def resolve(name):
    if name in NAME_MAP:
        return NAME_MAP[name]
    s = strip_tag(name)
    if s and s in NAME_MAP:
        return NAME_MAP[s]
    if name.lower() in NAME_MAP_LOWER:
        return NAME_MAP_LOWER[name.lower()]
    if s and s.lower() in NAME_MAP_LOWER:
        return NAME_MAP_LOWER[s.lower()]
    return None


def main():
    gtr = json.load(open(GTR_PATH, encoding='utf-8'))
    # Process active first, then unranked. Active takes priority because
    # an unranked entry is usually a legacy/alt account; the active one is
    # the player's current account.
    active = [n for n in gtr if n['rank'] > 0]
    unranked = [n for n in gtr if n['rank'] <= 0]
    seed = json.load(open(SEED_PATH, encoding='utf-8'))
    seed_size_before = len(seed)

    # Collect proposed merges, group by canonical. Active entries appended
    # first so when len(sids)>1 we know which one is active.
    proposals = defaultdict(list)  # canonical -> [(sid, gtr_name, is_active)]
    for n in active:
        c = resolve(n['steamName'])
        if c is None:
            continue
        proposals[c].append((n['steamId'], n['steamName'], True))
    for n in unranked:
        c = resolve(n['steamName'])
        if c is None:
            continue
        # Skip unranked if we already have an active hit for this canonical
        # (would always create a "conflict" we'd just resolve toward active).
        if any(active_hit[2] for active_hit in proposals[c]):
            continue
        proposals[c].append((n['steamId'], n['steamName'], False))

    added = 0
    skipped_existing = 0
    skipped_conflict = 0
    skipped_manual = 0
    overridden = 0
    for c, hits in proposals.items():
        if c in SKIP_CANONICALS:
            skipped_manual += 1
            continue
        if c in MANUAL_OVERRIDES:
            sid = MANUAL_OVERRIDES[c]
            overridden += 1
        else:
            sids = {h[0] for h in hits}
            if len(sids) > 1:
                skipped_conflict += 1
                print(f'  conflict, skipping {c}: {hits}')
                continue
            sid = hits[0][0]
        if c in seed:
            if seed[c] != sid:
                # GTR disagrees with our seed. Keep seed (TyO/livelog wins).
                print(f'  [keep seed] {c}: seed={seed[c]} vs gtr={sid}')
            skipped_existing += 1
            continue
        seed[c] = sid
        added += 1

    out_sorted = dict(sorted(seed.items(), key=lambda kv: kv[0].lower()))
    with open(SEED_PATH, 'w', encoding='utf-8') as f:
        json.dump(out_sorted, f, ensure_ascii=False, indent=2)

    print(f'\nsteam_ids.json: {seed_size_before} -> {len(out_sorted)} entries (+{added})')
    print(f'  added from GTR:        {added}')
    print(f'  added via override:    {overridden}  ({sorted(MANUAL_OVERRIDES)})')
    print(f'  already had a steamID: {skipped_existing}')
    print(f'  skipped (conflict):    {skipped_conflict}')
    print(f'  skipped (manual list): {skipped_manual}  ({sorted(SKIP_CANONICALS)})')

    # Coverage of qualified roster
    qualified = {p['n'] for p in alldata['weighted']
                 if p['c'] >= 5 or (p.get('g', 0) + p.get('s', 0) + p.get('z', 0)) > 0}
    have = qualified & set(out_sorted.keys())
    miss = qualified - set(out_sorted.keys())
    print(f'\nQualified COTD coverage: {len(have)}/{len(qualified)} '
          f'({len(have)*100//max(1,len(qualified))}%), {len(miss)} missing')


if __name__ == '__main__':
    main()
