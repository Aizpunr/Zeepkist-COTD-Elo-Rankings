"""Off-drive mirror of the COTD repo's un-versioned source of truth.

The master result spreadsheets (root *.xlsx), the recovery backups
(backups/**), the old snapshots (old snapshots/**) and the raw cup logs
(cup logs/*) are gitignored and exist only on this SSD. This script mirrors
them to a destination directory using the same relative layout, so a disk
failure does not take the only copy with it.

Managed sources (relative to this script's directory):
  *.xlsx                              root spreadsheets, copied as-is
  backups/**                          recursive, copied as-is
  old snapshots/**                    recursive, copied as-is
  cup logs/*                          copied as-is, except livelogs below
  cup logs/*_liveleaderboard.log      stored gzipped (level 9) as
                                      <dest>/cup logs/<name>.gz, the .gz
                                      carrying the source file's mtime

Plain files are copied only when missing in the destination or when their
(size, mtime) differ. Livelogs are re-gzipped only when the source
(size, mtime) recorded in <dest>/.livelog_index.json differ. Nothing is
ever deleted from the destination. After every run <dest>/MANIFEST.json is
rewritten with the sha1 of every managed file as stored in the destination;
--verify recomputes those hashes.

Config precedence (highest first):
  1. CLI      --dest DIR, --git
  2. env      COTD_BACKUP_DIR (destination only)
  3. file     backup_config.json next to this script:
              {"dest": "D:\\\\cotd-raw-backup", "git": false}
  4. none     instructions are printed and the script exits with code 2

Usage:
  python backup_raw_data.py [--dest DIR] [--git] [--dry-run] [--verify]

Exit codes:
  0  ok
  1  one or more per-file (or git) errors, run continued to the end
  2  not configured (no destination known)
"""

import sys

sys.stdout.reconfigure(encoding='utf-8')

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

REPO_DIR = Path(__file__).resolve().parent
CONFIG_NAME = "backup_config.json"
ENV_DEST = "COTD_BACKUP_DIR"
MANIFEST_NAME = "MANIFEST.json"
LIVELOG_INDEX_NAME = ".livelog_index.json"
LIVELOG_SUFFIX = "_liveleaderboard.log"
CUP_LOG_RE = re.compile(r"^cotd_(\d+)\.log$")

CONFIG_EXAMPLE = '{"dest": "D:\\\\cotd-raw-backup", "git": false}'


@dataclass
class BackupResult:
    copied: int = 0
    skipped: int = 0
    gzipped: int = 0
    gz_skipped: int = 0
    bytes_written: int = 0
    errors: list = field(default_factory=list)


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

def print_not_configured() -> None:
    print("backup_raw_data.py is not configured: no destination directory known.")
    print()
    print("Tell it where to mirror the raw data, using one of:")
    print("  1. CLI:  python backup_raw_data.py --dest \"D:\\cotd-raw-backup\"")
    print(f"  2. env:  set {ENV_DEST}=D:\\cotd-raw-backup")
    print(f"  3. file: create {REPO_DIR / CONFIG_NAME} with content:")
    print(f"           {CONFIG_EXAMPLE}")
    print("           (\"git\": true additionally runs git add/commit/push in dest)")
    print()
    print("Exit code 2 = not configured.")


def load_config(args: argparse.Namespace) -> tuple:
    """Return (dest: Path, git: bool). Exits with code 2 when no dest is known."""
    dest: Optional[str] = None
    git = False

    cfg_path = REPO_DIR / CONFIG_NAME
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"warning: could not read {cfg_path}: {exc}")
            cfg = {}
        if isinstance(cfg, dict):
            if cfg.get("dest"):
                dest = str(cfg["dest"])
            git = bool(cfg.get("git", False))

    env_dest = os.environ.get(ENV_DEST)
    if env_dest:
        dest = env_dest

    if args.dest:
        dest = args.dest
    if args.git:
        git = True

    if not dest:
        print_not_configured()
        sys.exit(2)

    return Path(dest), git


# --------------------------------------------------------------------------
# source enumeration
# --------------------------------------------------------------------------

def is_livelog(path: Path) -> bool:
    return path.name.endswith(LIVELOG_SUFFIX)


def collect_sources() -> tuple:
    """Return (plain: list[Path], livelogs: list[Path]) of absolute source files."""
    plain = []
    livelogs = []

    plain.extend(sorted(p for p in REPO_DIR.glob("*.xlsx") if p.is_file()))

    for sub in ("backups", "old snapshots"):
        root = REPO_DIR / sub
        if root.is_dir():
            plain.extend(sorted(p for p in root.rglob("*") if p.is_file()))

    cup_logs = REPO_DIR / "cup logs"
    if cup_logs.is_dir():
        for p in sorted(cup_logs.iterdir()):
            if not p.is_file():
                continue
            if is_livelog(p):
                livelogs.append(p)
            else:
                plain.append(p)

    return plain, livelogs


def latest_cup_number() -> Optional[int]:
    cup_logs = REPO_DIR / "cup logs"
    if not cup_logs.is_dir():
        return None
    nums = []
    for p in cup_logs.iterdir():
        m = CUP_LOG_RE.match(p.name)
        if m and p.is_file():
            nums.append(int(m.group(1)))
    return max(nums) if nums else None


def rel_of(path: Path) -> str:
    return path.relative_to(REPO_DIR).as_posix()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def sha1_of(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stat_differs(src: Path, dst: Path) -> bool:
    if not dst.exists():
        return True
    s, d = src.stat(), dst.stat()
    if s.st_size != d.st_size:
        return True
    # copy2 preserves mtime, allow tiny fs-resolution drift
    return abs(s.st_mtime - d.st_mtime) > 1e-3


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def gzip_file(src: Path, dst: Path) -> int:
    """Gzip src to dst at level 9, set dst mtime to src's. Return dst size."""
    st = src.stat()
    with open(src, "rb") as fin, open(dst, "wb") as raw:
        with gzip.GzipFile(filename=src.name, mode="wb", compresslevel=9,
                           fileobj=raw, mtime=int(st.st_mtime)) as gz:
            shutil.copyfileobj(fin, gz, 1024 * 1024)
    os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns))
    return dst.stat().st_size


# --------------------------------------------------------------------------
# backup
# --------------------------------------------------------------------------

def backup(dest: Path, git: bool, dry_run: bool) -> BackupResult:
    res = BackupResult()
    plain, livelogs = collect_sources()
    prefix = "[dry-run] " if dry_run else ""

    index_path = dest / LIVELOG_INDEX_NAME
    index = load_json(index_path)  # read-only, {} when absent

    managed_rel = []  # relative paths as stored in dest

    if not dry_run:
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            res.errors.append(f"cannot create destination {dest}: {exc}")

    # plain copies
    for src in plain:
        rel = rel_of(src)
        dst = dest / rel
        managed_rel.append(rel)
        try:
            if not stat_differs(src, dst):
                res.skipped += 1
                continue
            size = src.stat().st_size
            if dry_run:
                print(f"{prefix}copy   {rel} ({size:,} B)")
                res.copied += 1
                res.bytes_written += size
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            res.copied += 1
            res.bytes_written += size
        except Exception as exc:
            res.errors.append(f"copy {rel}: {exc}")

    # livelogs, gzipped
    for src in livelogs:
        rel_gz = rel_of(src) + ".gz"
        dst = dest / rel_gz
        managed_rel.append(rel_gz)
        try:
            st = src.stat()
            recorded = index.get(rel_gz) or {}
            rec_mtime = recorded.get("src_mtime")
            unchanged = (
                dst.exists()
                and recorded.get("src_size") == st.st_size
                and isinstance(rec_mtime, (int, float))
                and abs(rec_mtime - st.st_mtime) <= 1e-3
            )
            if unchanged:
                res.gz_skipped += 1
                continue
            if dry_run:
                print(f"{prefix}gzip   {rel_gz} (src {st.st_size:,} B)")
                res.gzipped += 1
                res.bytes_written += st.st_size
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            written = gzip_file(src, dst)
            index[rel_gz] = {"src_size": st.st_size, "src_mtime": st.st_mtime}
            res.gzipped += 1
            res.bytes_written += written
        except Exception as exc:
            res.errors.append(f"gzip {rel_gz}: {exc}")

    if dry_run:
        print(f"{prefix}skipped {res.skipped} plain files and "
              f"{res.gz_skipped} livelogs already up to date")
        print(f"{prefix}would copy {res.copied} files and gzip {res.gzipped} "
              f"livelogs, about {res.bytes_written / 1e6:.1f} MB of source data")
        return res

    # livelog index
    try:
        write_json(index_path, index)
    except Exception as exc:
        res.errors.append(f"write {LIVELOG_INDEX_NAME}: {exc}")

    # manifest, always rewritten
    entries = []
    for rel in managed_rel:
        p = dest / rel
        try:
            if not p.exists():
                continue
            entries.append({"rel": rel, "size": p.stat().st_size, "sha1": sha1_of(p)})
        except Exception as exc:
            res.errors.append(f"hash {rel}: {exc}")
    manifest = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "repo": str(REPO_DIR),
        "latest_cup": latest_cup_number(),
        "entries": entries,
    }
    try:
        write_json(dest / MANIFEST_NAME, manifest)
    except Exception as exc:
        res.errors.append(f"write {MANIFEST_NAME}: {exc}")

    if git:
        run_git(dest, res)

    return res


def run_git(dest: Path, res: BackupResult) -> None:
    cup = latest_cup_number()
    msg = f"COTD raw data {datetime.now():%Y-%m-%d} (cup {cup if cup is not None else '?'})"
    steps = [
        ("add", ["git", "-C", str(dest), "add", "-A"]),
        ("commit", ["git", "-C", str(dest), "commit", "-m", msg]),
        ("push", ["git", "-C", str(dest), "push"]),
    ]
    for name, cmd in steps:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except Exception as exc:
            res.errors.append(f"git {name}: {exc}")
            continue
        out = (proc.stdout + proc.stderr).strip()
        if proc.returncode == 0:
            print(f"git {name}: ok")
            continue
        if name == "commit" and "nothing to commit" in out:
            print("git commit: nothing to commit")
            continue
        res.errors.append(f"git {name} failed (rc {proc.returncode}): {out[-500:]}")


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------

def verify(dest: Path) -> int:
    manifest_path = dest / MANIFEST_NAME
    if not manifest_path.exists():
        print(f"no {MANIFEST_NAME} in {dest}")
        return 1
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"cannot read {manifest_path}: {exc}")
        return 1

    entries = manifest.get("entries", [])
    problems = 0
    ok = 0
    for e in entries:
        rel = e.get("rel", "?")
        p = dest / rel
        if not p.exists():
            print(f"MISSING  {rel}")
            problems += 1
            continue
        try:
            actual = sha1_of(p)
        except Exception as exc:
            print(f"ERROR    {rel}: {exc}")
            problems += 1
            continue
        if actual != e.get("sha1"):
            print(f"MISMATCH {rel}")
            problems += 1
        else:
            ok += 1

    if problems == 0:
        print(f"OK: {ok} files verified")
        return 0
    print(f"FAILED: {problems} problem(s), {ok} files ok")
    return 1


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Mirror the COTD repo's gitignored raw data to a destination directory.")
    ap.add_argument("--dest", help="destination directory (overrides env and config)")
    ap.add_argument("--git", action="store_true",
                    help="after mirroring, git add/commit/push inside the destination")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be done, write nothing")
    ap.add_argument("--verify", action="store_true",
                    help="verify destination against its MANIFEST.json instead of backing up")
    args = ap.parse_args(argv)

    dest, git = load_config(args)

    if args.verify:
        return verify(dest)

    t0 = time.perf_counter()
    res = backup(dest, git, args.dry_run)
    elapsed = time.perf_counter() - t0

    for err in res.errors:
        print(f"ERROR: {err}")

    mode = "dry-run: " if args.dry_run else ""
    verb = "to write" if args.dry_run else "written"
    print(f"{mode}copied {res.copied}, skipped {res.skipped}, "
          f"gzipped {res.gzipped} (gz skipped {res.gz_skipped}), "
          f"{res.bytes_written / 1e6:.1f} MB {verb}, "
          f"errors {len(res.errors)}, {elapsed:.1f} s")
    return 1 if res.errors else 0


if __name__ == "__main__":
    sys.exit(main())
