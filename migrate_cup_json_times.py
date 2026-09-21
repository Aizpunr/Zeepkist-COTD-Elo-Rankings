"""migrate_cup_json_times.py: one-shot conversion of cup_<N>.json times to ms.

    python migrate_cup_json_times.py [--dry-run]

Until this change, cup_<N>.json stored each player's elimination time as the
raw string copied from the game log, so the decimal separator depended on the
locale of whichever PC produced the log ("45,05365" vs "43.34747"). The xlsx
path already normalized to integer milliseconds; the JSON now does too via
cotd_parser.time_to_ms(), the same function new_cup.py uses. 'DNF' stays the
string 'DNF'.

Idempotent: values that are already integers are left alone, so a second run
converts nothing. Originals are copied to backups/cup_json_pre_ms/ before the
first write (several early cup files are untracked, so git is not their
backup). Files are rewritten with the exact json.dump settings new_cup.py
uses, so a git diff shows only the "time" lines.
"""
import glob
import json
import os

import cup_paths
import shutil
import sys

sys.stdout.reconfigure(encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cotd_parser import time_to_ms  # noqa: E402

BACKUP_DIR = os.path.join(HERE, 'backups', 'cup_json_pre_ms')


def convert(doc):
    """Return (converted_count, already_int_count, dnf_count)."""
    conv = kept = dnf = 0
    for p in doc.get('players', []):
        t = p.get('time')
        if t == 'DNF':
            dnf += 1
        elif isinstance(t, int):
            kept += 1
        else:
            p['time'] = time_to_ms(t)
            conv += 1
    return conv, kept, dnf


def main(argv):
    dry = '--dry-run' in argv
    files = cup_paths.all_cup_json(HERE)
    total_conv = 0
    for path in files:
        with open(path, encoding='utf-8') as f:
            doc = json.load(f)
        conv, kept, dnf = convert(doc)
        name = os.path.basename(path)
        print(f"{name:<14} convert={conv:<3} already_int={kept:<3} dnf={dnf}")
        total_conv += conv
        if conv == 0 or dry:
            continue
        os.makedirs(BACKUP_DIR, exist_ok=True)
        bak = os.path.join(BACKUP_DIR, name)
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
    print()
    print(f"{'would convert' if dry else 'converted'} {total_conv} time values across {len(files)} files")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
