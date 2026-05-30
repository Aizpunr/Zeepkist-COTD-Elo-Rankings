"""
build_players_master.py — generate players.json (the master player registry).

Sources merged:
  - COTD   elo_engine.py CANONICAL + steam_ids.json
  - Eggy   elo_engine.py CANONICAL + steam_ids.json
  - Kerki  build_kerki.py CANONICAL (no steam_ids file)

Output: players.json in this folder. Shape:
    {
      "<canonical name>": {
        "steam_id": "76561...",   # or null if unknown
        "aliases":  ["[TAG]Name", "Name2", ...]
      },
      ...
    }

Re-run any time canonical or steam_ids change in any comp. The script is
idempotent: aliases are unioned per canonical name; steam_id keeps the first
non-null value seen (COTD first, then Eggy).
"""
import ast
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent   # ...\Desktop\Claude

SOURCES = [
    {
        'name': 'cotd',
        'engine': HERE / 'elo_engine.py',
        'steam_ids': HERE / 'steam_ids.json',
    },
    {
        'name': 'eggy',
        'engine': ROOT / 'eggy cup' / 'elo_engine.py',
        'steam_ids': ROOT / 'eggy cup' / 'steam_ids.json',
    },
    {
        'name': 'kerki',
        'engine': ROOT / 'kerki' / 'build_kerki.py',
        'steam_ids': None,
    },
]


def extract_canonical(py_path: Path) -> dict:
    """Parse a Python file and return the value of its top-level CANONICAL dict.

    Uses AST to safely evaluate without executing the file."""
    src = py_path.read_text(encoding='utf-8')
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'CANONICAL':
                    return ast.literal_eval(node.value)
    raise RuntimeError(f'No CANONICAL = {{...}} found in {py_path}')


def main():
    players: dict[str, dict] = {}

    for src in SOURCES:
        if not src['engine'].exists():
            print(f"  ! missing engine: {src['engine']}", file=sys.stderr)
            continue
        canon = extract_canonical(src['engine'])
        print(f"  {src['name']:6} canonical: {len(canon)} entries")
        for name, aliases in canon.items():
            entry = players.setdefault(name, {'steam_id': None, 'aliases': []})
            for a in aliases:
                if a not in entry['aliases']:
                    entry['aliases'].append(a)

    # Steam IDs: keyed by canonical name OR any known alias.
    # First non-null wins per canonical.
    for src in SOURCES:
        sid_path = src['steam_ids']
        if not sid_path or not sid_path.exists():
            continue
        ids = json.loads(sid_path.read_text(encoding='utf-8'))
        attached = 0
        unattached = []
        for raw_name, sid in ids.items():
            target = _resolve_canonical(raw_name, players)
            if target is None:
                # Name we don't know — register as a new canonical with no aliases
                players[raw_name] = {'steam_id': sid, 'aliases': []}
                unattached.append(raw_name)
            elif players[target]['steam_id'] is None:
                players[target]['steam_id'] = sid
                attached += 1
        print(f"  {src['name']:6} steam_ids: {len(ids)} entries "
              f"({attached} attached, {len(unattached)} added as new canonicals)")

    # Sort alphabetically (case-insensitive) for stable diffs
    ordered = dict(sorted(players.items(), key=lambda kv: kv[0].lower()))

    out_path = HERE / 'players.json'
    out_path.write_text(
        json.dumps(ordered, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )
    with_sid = sum(1 for v in ordered.values() if v['steam_id'])
    print(f"\nWrote {out_path.name}: {len(ordered)} players "
          f"({with_sid} with steam_id, {len(ordered) - with_sid} without)")


def _resolve_canonical(raw: str, players: dict) -> str | None:
    """Match a raw player name to a canonical. Tries exact canonical match,
    then alias match, then tag-stripped match."""
    if raw in players:
        return raw
    for canon, entry in players.items():
        if raw in entry['aliases']:
            return canon
    stripped = re.sub(r'\[.*?\]\s*', '', raw).strip()
    if stripped and stripped != raw and stripped in players:
        return stripped
    return None


if __name__ == '__main__':
    main()
