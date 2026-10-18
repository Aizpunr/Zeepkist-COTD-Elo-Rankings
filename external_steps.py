"""external_steps.py: the pipeline steps that write OUTSIDE this repo.

Called by new_cup.py (steps 8, 8b, 9b) and by catch_up.py after a cup was
processed online. They need this PC: the cross-comp and SOF repos and the
backup drive are not on GitHub. Each is non-fatal and returns True on success.
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))

CROSSCOMP_SCRIPT = r"C:\Users\rafa\Desktop\Claude\zeepkist holistic\refresh.py"
SOF_POOL = r"C:\Users\rafa\Desktop\Claude\zeepkist mod\Zeepkist-Strength-of-Field\elo_pool.json"
COTD_POOL_SCRIPT = r"C:\Users\rafa\Desktop\Claude\zeepkist mod\gtr_analysis\join_cotd_gtr.py"
SOF_COTD_POOL = r"C:\Users\rafa\Desktop\Claude\zeepkist mod\Zeepkist-Strength-of-Field\elo_pool_cotd.json"


def _banner(text):
    print("=" * 50)
    print(text)
    print("=" * 50)


def refresh_crosscomp():
    """Cross-comp ranking: allsofdata.json, allcompdata.json and the SOF mod's
    elo_pool.json (cross-comp ELO first, GTR rank regression as fallback)."""
    _banner("Refreshing cross-comp ranking + SOF data...")
    ok = False
    if os.path.exists(CROSSCOMP_SCRIPT):
        r = subprocess.run([sys.executable, CROSSCOMP_SCRIPT], cwd=os.path.dirname(CROSSCOMP_SCRIPT))
        if r.returncode == 0:
            print("  Cross-comp + SOF elo_pool.json refreshed.")
            ok = True
        else:
            print(f"  WARNING: cross-comp refresh failed (returncode={r.returncode}).")
            print(f"  Run manually: python \"{CROSSCOMP_SCRIPT}\"")
    else:
        print(f"  SKIP: refresh script not found at {CROSSCOMP_SCRIPT}")
    print()
    return ok


def refresh_cotd_pool():
    """elo_pool_cotd.json, the mod's `!sof cup` data. It hits graphql.zeepki.st,
    so a GTR outage must not break cup processing."""
    _banner("Refreshing COTD SOF pool (mod's !sof cup data)...")
    ok = False
    if os.path.exists(COTD_POOL_SCRIPT):
        r = subprocess.run([sys.executable, COTD_POOL_SCRIPT], cwd=os.path.dirname(COTD_POOL_SCRIPT))
        if r.returncode == 0:
            print("  COTD elo_pool_cotd.json refreshed.")
            ok = True
        else:
            print(f"  WARNING: COTD pool refresh failed (returncode={r.returncode}).")
            print(f"  Run manually: python \"{COTD_POOL_SCRIPT}\"")
    else:
        print(f"  SKIP: COTD pool script not found at {COTD_POOL_SCRIPT}")
    print()
    return ok


def backup_raw_data():
    """Mirror the gitignored files (xlsx backups, raw cup logs, backups/)
    off-drive with backup_raw_data.py. Never fatal, but shouted."""
    _banner("Backing up raw data (xlsx, cup logs, backups/)...")
    script = os.path.join(BASE, 'backup_raw_data.py')
    ok = False
    if os.path.exists(script):
        r = subprocess.run([sys.executable, script], cwd=BASE)
        if r.returncode == 0:
            ok = True
        elif r.returncode == 2:
            print("  raw-data backup not configured: create backup_config.json (see backup_raw_data.py)")
        else:
            print("  " + "!" * 60)
            print("  !! RAW DATA BACKUP FAILED. Run: python backup_raw_data.py")
            print("  " + "!" * 60)
    else:
        print("  SKIP: backup_raw_data.py not found")
    print()
    return ok


def sof_push_reminder(sof_ok, cotd_pool_ok):
    if not (sof_ok or cotd_pool_ok):
        return
    print("  - Git commit + push (SOF repo) — stage all three:")
    if sof_ok:
        print(f"      {SOF_POOL}")
    if cotd_pool_ok:
        print(f"      {SOF_COTD_POOL}")
    print("      docs/allcompdata.json (cross-comp site data — easy to miss)")
