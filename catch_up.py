"""catch_up.py: run on the PC after cups were processed online.

The GitHub Action (submissions_poll.py --ci) publishes a cup through a merged
pull request, but some steps need this PC. This script runs them:

  1. git pull --ff-only (main)
  2. fetch the raw logs of online cups from the Worker into cup logs/
     (needs submit_config.json; the backup should hold every raw log)
  3. sync_xlsx.py: bring the xlsx backups in line with results/
  4. cross-comp ranking + SOF pools (external_steps.py)
  5. raw-data backup off-drive

The cross-comp and SOF repo pushes stay manual, as after new_cup.py.

  python catch_up.py [--no-pull] [--no-external]
"""
import json
import os
import subprocess
import sys
import types

import external_steps
import sync_xlsx

BASE = os.path.dirname(os.path.abspath(__file__))


def pull():
    branch = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=BASE,
                            capture_output=True, text=True).stdout.strip()
    if branch != 'main':
        print(f'ERROR: on branch {branch!r}, not main; switch first.')
        return False
    r = subprocess.run(['git', 'pull', '--ff-only'], cwd=BASE)
    if r.returncode != 0:
        print('ERROR: git pull --ff-only failed (local changes or a diverged main); sort it out first.')
        return False
    return True


def fetch_raw_logs():
    """Raw logs of submitted cups that are in cup_meta.json but not in cup logs/."""
    cfg_path = os.path.join(BASE, 'submit_config.json')
    if not os.path.exists(cfg_path):
        print('  SKIP: no submit_config.json, raw logs not fetched')
        return
    import submissions_poll as sp
    with open(cfg_path, encoding='utf-8') as f:
        cfg = json.load(f)
    ctx = types.SimpleNamespace(worker=cfg['worker_url'].rstrip('/'), token=cfg['poller_token'])
    with open(os.path.join(BASE, 'cup_meta.json'), encoding='utf-8') as f:
        meta = json.load(f)
    try:
        subs = sp.api(ctx, 'GET', '/status').get('submissions', [])
    except sp.WorkerError as e:
        print(f'  WARNING: Worker unreachable, raw logs not fetched: {e}')
        return
    for sub in subs:
        if sub.get('status') not in ('processed', 'published') or f"COTD {sub['cup']}" not in meta:
            continue
        dest = os.path.join(BASE, 'cup logs', f"cotd_{sub['cup']}.log")
        if os.path.exists(dest):
            continue
        try:
            data, _ = sp.api(ctx, 'GET', '/log/' + sub['id'], raw=True, timeout=120)
        except sp.WorkerError as e:
            print(f"  WARNING: COTD {sub['cup']} log not fetched: {e}")
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, 'wb') as f:
            f.write(data)
        print(f"  cup logs/cotd_{sub['cup']}.log ({len(data) // 1024} KB, submission {sub['id']})")


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    if '--no-pull' not in sys.argv and not pull():
        return 1
    print('=' * 50)
    print('Fetching raw logs of online cups...')
    print('=' * 50)
    fetch_raw_logs()
    print()
    print('=' * 50)
    print('Syncing the xlsx backups...')
    print('=' * 50)
    rc = sync_xlsx.main()
    print()
    if '--no-external' not in sys.argv:
        sof_ok = external_steps.refresh_crosscomp()
        cotd_pool_ok = external_steps.refresh_cotd_pool()
        external_steps.backup_raw_data()
        print('Next steps:')
        if sof_ok or cotd_pool_ok:
            external_steps.sof_push_reminder(sof_ok, cotd_pool_ok)
        else:
            print('  - nothing to push from the SOF repo')
    return rc


if __name__ == '__main__':
    sys.exit(main())
