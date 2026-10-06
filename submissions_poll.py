"""submissions_poll.py: process cups submitted on submit.html, unattended.

Run by Windows Task Scheduler every 15 minutes (see SUBMIT.md). Each pass:

  1. Asks the cotd-submit Worker for pending submissions.
  2. Marks 'processed' cups that are now on origin/main as 'published'.
  3. For 'received' ones: downloads the log, skips cups that are already
     processed ('duplicate'), keeps the most complete log when several were
     sent for one cup ('superseded'), and runs
        new_cup.py N "<mapper>" --map ... --date ... --log <file> --no-open
     for AT MOST ONE cup per pass.
  4. Posts the outcome ('processed' with a summary, or 'failed' with the
     ERROR line) back to the Worker, and shows a Windows toast.

It never pushes, never commits and never passes --reprocess. Publishing stays
manual: verify on http://localhost:8000, then commit and push as usual.

Config: submit_config.json next to this script (gitignored):
    {"worker_url": "https://cotd-submit.<you>.workers.dev",
     "poller_token": "<same value as the Worker's POLLER_TOKEN secret>"}
Optional keys: repo_dir, python, toast (true), git_remote ("origin"),
git_branch ("main").

Files live in "cup logs/submissions/" (gitignored): downloaded logs,
new_cup.py output (<id>.out), state.json, poll.log, and a PAUSE marker: while
a file named PAUSE exists there, every pass exits at once (use it when you
process a cup by hand).

Usage:
  python submissions_poll.py [--once] [--dry-run] [--repo DIR] [--worker URL]
                             [--id ID] [--no-git] [--reindex] [--rehearsal]
                             [--loop SECONDS] [-v]
"""
import argparse
import base64
import datetime
import hashlib
import json
import logging
import logging.handlers
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
HEADER = 'Doing eliminations with leaderboard'
LOCK_STALE_S = 2 * 3600
NEW_CUP_TIMEOUT_S = 1800

log = logging.getLogger('submissions_poll')


# ── config and paths ─────────────────────────────────────────────────

class Ctx:
    def __init__(self, args):
        cfg_path = os.path.join(HERE, 'submit_config.json')
        cfg = {}
        if os.path.exists(cfg_path):
            with open(cfg_path, encoding='utf-8') as f:
                cfg = json.load(f)
        self.worker = (args.worker or cfg.get('worker_url') or '').rstrip('/')
        self.token = os.environ.get('COTD_POLLER_TOKEN') or cfg.get('poller_token') or ''
        self.repo = os.path.abspath(args.repo or cfg.get('repo_dir') or HERE)
        self.python = cfg.get('python') or sys.executable
        # pythonw.exe (Task Scheduler) has no console; new_cup.py needs a real
        # interpreter only for its own children, and python.exe works either way.
        if os.path.basename(self.python).lower() == 'pythonw.exe':
            self.python = os.path.join(os.path.dirname(self.python), 'python.exe')
        self.toast = cfg.get('toast', True)
        self.remote = cfg.get('git_remote', 'origin')
        self.branch = cfg.get('git_branch', 'main')
        self.dry_run = args.dry_run
        self.no_git = args.no_git
        self.only_id = args.id
        self.rehearsal = args.rehearsal
        self.subdir = os.path.join(self.repo, 'cup logs', 'submissions')
        os.makedirs(self.subdir, exist_ok=True)
        self.state_path = os.path.join(self.subdir, 'state.json')
        self.state = load_json(self.state_path, {})

    def save_state(self):
        if self.dry_run:
            return
        tmp = self.state_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.state_path)


def load_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def setup_logging(subdir, verbose):
    log.setLevel(logging.DEBUG)
    fmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s', '%Y-%m-%d %H:%M:%S')
    fh = logging.handlers.RotatingFileHandler(os.path.join(subdir, 'poll.log'), maxBytes=1_000_000,
                                              backupCount=3, encoding='utf-8')
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG if verbose else logging.INFO)
    log.addHandler(fh)
    if sys.stdout is not None:  # None under pythonw.exe
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            pass
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        sh.setLevel(logging.DEBUG if verbose else logging.INFO)
        log.addHandler(sh)


# ── lock ─────────────────────────────────────────────────────────────

def acquire_lock(path):
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f'{os.getpid()} {time.time():.0f}'.encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                started = float(open(path).read().split()[1])
            except (OSError, IndexError, ValueError):
                started = 0
            if time.time() - started < LOCK_STALE_S:
                return False
            log.warning('removing stale lock (%s)', path)
            try:
                os.remove(path)
            except OSError:
                return False
    return False


# ── Worker API ───────────────────────────────────────────────────────

class WorkerError(Exception):
    pass


def _ssl_context():
    """Prefer certifi's CA bundle: this PC's Windows store only has an expired
    cross-signed path to Let's Encrypt's newer chains, which workers.dev uses,
    so the default context fails with 'certificate has expired'."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_CTX = _ssl_context()


def api(ctx, method, path, body=None, raw=False, timeout=30):
    url = ctx.worker + path
    data = None
    headers = {'Authorization': 'Bearer ' + ctx.token, 'User-Agent': 'cotd-submissions-poll'}
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
            payload = r.read()
            if raw:
                return payload, dict(r.headers)
            return json.loads(payload.decode('utf-8'))
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'replace')[:300]
        raise WorkerError(f'{method} {path}: HTTP {e.code} {detail}')
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise WorkerError(f'{method} {path}: {e}')


def post_status(ctx, sid, status, note='', summary=None):
    """Record the outcome locally first, then tell the Worker. A failed POST
    stays in state.json with posted=False and is retried next pass."""
    entry = ctx.state.setdefault(sid, {})
    entry.update({'status': status, 'note': note, 'summary': summary, 'posted': False,
                  'at': datetime.datetime.now().isoformat(timespec='seconds')})
    if ctx.dry_run:
        log.info('[dry-run] would POST /status/%s %s %s', sid, status, note)
        return
    ctx.save_state()
    body = {'status': status, 'note': note}
    if summary is not None:
        body['summary'] = summary
    try:
        api(ctx, 'POST', '/status/' + sid, body)
        entry['posted'] = True
        ctx.save_state()
        log.info('status %s -> %s %s', sid, status, note)
    except WorkerError as e:
        log.warning('could not post status for %s (will retry): %s', sid, e)


def retry_unposted(ctx):
    for sid, entry in ctx.state.items():
        if sid.startswith('_'):
            continue
        if entry.get('posted') is False and entry.get('status'):
            try:
                body = {'status': entry['status'], 'note': entry.get('note', '')}
                if entry.get('summary') is not None:
                    body['summary'] = entry['summary']
                if ctx.dry_run:
                    log.info('[dry-run] would retry status %s', sid)
                    continue
                api(ctx, 'POST', '/status/' + sid, body)
                entry['posted'] = True
                log.info('retried status %s -> %s', sid, entry['status'])
            except WorkerError as e:
                log.warning('retry failed for %s: %s', sid, e)
    ctx.save_state()


# ── git: which cups are published ────────────────────────────────────

def published_cups(ctx):
    if ctx.no_git:
        return None
    try:
        subprocess.run(['git', 'fetch', ctx.remote, '--quiet'], cwd=ctx.repo, timeout=60,
                       capture_output=True, check=True)
        r = subprocess.run(['git', 'show', f'{ctx.remote}/{ctx.branch}:cup_meta.json'], cwd=ctx.repo,
                           timeout=30, capture_output=True, check=True)
        return set(json.loads(r.stdout.decode('utf-8')).keys())
    except (subprocess.SubprocessError, OSError, ValueError) as e:
        log.warning('publish detection skipped: %s', e)
        return None


# ── helpers ──────────────────────────────────────────────────────────

def count_blocks(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return sum(1 for line in f if 'COTDTracker' in line and HEADER in line)
    except OSError:
        return 0


def unsafe_args(sub):
    vals = [sub.get('mapper', ''), sub.get('map', '')] + list(sub.get('exclude') or [])
    for v in vals:
        if not isinstance(v, str) or not v.strip() or v.startswith('--') or re.search(r'[\r\n\0]', v):
            return f'unsafe argument {v!r}'
    for v in sub.get('exclude') or []:
        if ',' in v:
            return f'excluded name {v!r} contains a comma'
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(sub.get('date', ''))):
        return 'bad date'
    if not isinstance(sub.get('cup'), int):
        return 'bad cup number'
    return None


def download(ctx, sub):
    path = os.path.join(ctx.subdir, f"{sub['id']}_cotd_{sub['cup']}.log")
    if os.path.exists(path) and sha256_file(path) == sub.get('sha256'):
        return path
    data, headers = api(ctx, 'GET', '/log/' + sub['id'], raw=True, timeout=120)
    got = hashlib.sha256(data).hexdigest()
    want = sub.get('sha256') or headers.get('X-Sha256') or headers.get('x-sha256')
    if want and got != want:
        raise WorkerError(f"sha256 mismatch for {sub['id']}: {got} != {want}")
    with open(path, 'wb') as f:
        f.write(data)
    return path


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def toast(ctx, title, body):
    if not ctx.toast or ctx.dry_run:
        return
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null;"
        "$t = [System.Security.SecurityElement]::Escape('" + title.replace("'", "''") + "');"
        "$b = [System.Security.SecurityElement]::Escape('" + body.replace("'", "''") + "');"
        "$x = New-Object Windows.Data.Xml.Dom.XmlDocument;"
        "$x.LoadXml(\"<toast><visual><binding template='ToastGeneric'><text>$t</text><text>$b</text></binding></visual></toast>\");"
        "$n = [Windows.UI.Notifications.ToastNotification]::new($x);"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe').Show($n);"
    )
    try:
        enc = base64.b64encode(ps.encode('utf-16-le')).decode('ascii')
        subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-EncodedCommand', enc],
                       timeout=20, capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (subprocess.SubprocessError, OSError) as e:
        log.debug('toast failed: %s', e)


# ── running new_cup.py ───────────────────────────────────────────────

def new_cup_command(ctx, sub, log_path):
    cmd = [ctx.python, os.path.join(ctx.repo, 'new_cup.py'), str(sub['cup']), sub['mapper'],
           '--map', sub['map']]
    exclude = [x for x in (sub.get('exclude') or []) if x != sub['mapper']]
    if exclude:
        cmd += ['--exclude', ','.join(exclude)]
    cmd += ['--date', sub['date'], '--log', log_path, '--no-open']
    return cmd


def summarize(ctx, cup, out_text):
    summary = {'winner': None, 'podium': [], 'players': None, 'rounds': None, 'warnings': []}
    cup_json = os.path.join(ctx.repo, 'cup_data', f'cup_{cup}.json')
    doc = load_json(cup_json, None)
    if doc and doc.get('players'):
        players = doc['players']
        summary['winner'] = players[0]['name']
        summary['podium'] = [{'name': p['name'], 'time': p['time']} for p in players[:3]]
        summary['players'] = len(players)
        summary['rounds'] = max((p['round'] or 0) for p in players)
    warnings = []
    lines = out_text.splitlines()
    in_failed = False
    for line in lines:
        s = line.strip()
        if s.startswith('⚠'):
            warnings.append(s.lstrip('⚠').strip())
        if 'non-fatal step' in s and 'FAILED' in s:
            in_failed = True
            warnings.append(s.strip('! ').strip())
            continue
        if in_failed:
            if s.startswith('- '):
                warnings.append('failed step: ' + s[2:])
            else:
                in_failed = False
        if 'RAW DATA BACKUP FAILED' in s:
            warnings.append('raw data backup failed')
    summary['warnings'] = warnings[:20]
    return summary


def run_cup(ctx, sub, log_path):
    sid, cup = sub['id'], sub['cup']
    cmd = new_cup_command(ctx, sub, log_path)
    log.info('running: %s', subprocess.list2cmdline(cmd))
    if ctx.dry_run:
        log.info('[dry-run] new_cup.py not run')
        return
    out_path = os.path.join(ctx.subdir, f'{sid}.out')
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    if ctx.rehearsal:
        env['COTD_SKIP_EXTERNAL'] = '1'
    ctx.state.setdefault(sid, {})['started'] = datetime.datetime.now().isoformat(timespec='seconds')
    ctx.save_state()
    try:
        with open(out_path, 'wb') as out:
            r = subprocess.run(cmd, cwd=ctx.repo, stdout=out, stderr=subprocess.STDOUT, env=env,
                               timeout=NEW_CUP_TIMEOUT_S,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        rc = r.returncode
    except subprocess.TimeoutExpired:
        post_status(ctx, sid, 'failed', f'new_cup.py timed out after {NEW_CUP_TIMEOUT_S // 60} min; aizpun must check it')
        toast(ctx, f'COTD {cup} FAILED', 'new_cup.py timed out')
        return
    with open(out_path, encoding='utf-8', errors='replace') as f:
        out_text = f.read()

    if rc == 0 and f'COTD {cup} COMPLETE' in out_text:
        summary = summarize(ctx, cup, out_text)
        post_status(ctx, sid, 'processed', 'awaiting publish', summary)
        who = sub.get('submitter') or 'someone'
        toast(ctx, f'COTD {cup} processed',
              f"Sent by {who}. Winner {summary['winner']}, {summary['players']} players. Verify localhost:8000, then push.")
        return

    errors = [l.strip() for l in out_text.splitlines() if l.strip().startswith('ERROR')]
    if errors:
        note = errors[-1]
    else:
        tail = [l.strip() for l in out_text.splitlines() if l.strip()][-3:]
        note = ' | '.join(tail) or f'new_cup.py exited with code {rc}'
    note = note[:500]
    if 'is already processed' in note and ctx.state.get(sid, {}).get('status') == 'processed':
        post_status(ctx, sid, 'processed', 'awaiting publish', ctx.state[sid].get('summary'))
        return
    post_status(ctx, sid, 'failed', note)
    toast(ctx, f'COTD {cup} FAILED', note[:200])


# ── one pass ─────────────────────────────────────────────────────────

def one_pass(ctx, args):
    if os.path.exists(os.path.join(ctx.subdir, 'PAUSE')):
        log.info('PAUSE marker present, skipping this pass')
        return 0
    if not ctx.worker or not ctx.token:
        log.error('worker_url / poller_token missing: create submit_config.json (see SUBMIT.md)')
        return 2
    lock = os.path.join(ctx.subdir, '.lock')
    if not ctx.dry_run and not acquire_lock(lock):
        log.info('another pass is running, exiting')
        return 0
    try:
        return _pass(ctx, args)
    finally:
        if not ctx.dry_run:
            try:
                os.remove(lock)
            except OSError:
                pass


def _pass(ctx, args):
    # Rebuild the Worker's index once a day (after 04:00) as a sweep for
    # records a concurrent write may have dropped from it; or on --reindex.
    meta = ctx.state.setdefault('_meta', {})
    today = datetime.date.today().isoformat()
    if args.reindex or (meta.get('last_reindex') != today and datetime.datetime.now().hour >= 4):
        try:
            if ctx.dry_run:
                log.info('[dry-run] would POST /reindex')
            else:
                log.info('reindex: %s', api(ctx, 'POST', '/reindex'))
                meta['last_reindex'] = today
                ctx.save_state()
        except WorkerError as e:
            log.warning('reindex failed: %s', e)

    retry_unposted(ctx)
    try:
        pending = api(ctx, 'GET', '/pending').get('submissions', [])
    except WorkerError as e:
        log.warning('worker unreachable, nothing done: %s', e)
        return 0
    if ctx.only_id:
        pending = [s for s in pending if s['id'] == ctx.only_id]
    log.debug('%d pending submission(s)', len(pending))
    if not pending:
        return 0

    local_meta = set(load_json(os.path.join(ctx.repo, 'cup_meta.json'), {}).keys())
    remote_meta = published_cups(ctx)

    # processed -> published once the cup is on the remote branch
    for sub in pending:
        if sub['status'] == 'processed' and remote_meta is not None and f"COTD {sub['cup']}" in remote_meta:
            post_status(ctx, sub['id'], 'published', '', sub.get('summary'))

    received = [s for s in pending if s['status'] == 'received'
                and ctx.state.get(s['id'], {}).get('status') not in ('processed', 'failed', 'duplicate', 'superseded')]
    if not received:
        return 0

    by_cup = {}
    for sub in sorted(received, key=lambda s: s['created']):
        by_cup.setdefault(sub['cup'], []).append(sub)

    ran = False
    for cup in sorted(by_cup):
        subs = by_cup[cup]
        blocks = {}
        paths = {}
        for sub in subs:
            try:
                paths[sub['id']] = download(ctx, sub)
            except (WorkerError, OSError) as e:
                log.warning('download failed for %s: %s', sub['id'], e)
                continue
            blocks[sub['id']] = count_blocks(paths[sub['id']])
        subs = [s for s in subs if s['id'] in paths]
        if not subs:
            continue

        cup_id = f'COTD {cup}'
        if cup_id in local_meta or (remote_meta is not None and cup_id in remote_meta):
            existing = os.path.join(ctx.repo, 'cup logs', f'cotd_{cup}.log')
            have = count_blocks(existing) if os.path.exists(existing) else 0
            for sub in subs:
                n = blocks[sub['id']]
                note = f'{cup_id} is already processed ({n} leaderboards in this log vs {have} in the one used)'
                if n > have:
                    note = 'REVIEW: ' + note
                    toast(ctx, f'{cup_id}: a more complete log arrived', note)
                post_status(ctx, sub['id'], 'duplicate', note)
            continue

        best = max(subs, key=lambda s: (blocks[s['id']], -subs.index(s)))
        for sub in subs:
            if sub is not best:
                post_status(ctx, sub['id'], 'superseded',
                            f"superseded by {best['id']} ({blocks[best['id']]} vs {blocks[sub['id']]} leaderboards)")

        problem = unsafe_args(best)
        if problem:
            post_status(ctx, best['id'], 'failed', f'{problem}; aizpun must process this cup by hand')
            continue

        if ran:
            log.info('%s waits for the next pass (one cup per pass)', cup_id)
            continue
        run_cup(ctx, best, paths[best['id']])
        ran = True
        local_meta = set(load_json(os.path.join(ctx.repo, 'cup_meta.json'), {}).keys())
    return 0


def main():
    ap = argparse.ArgumentParser(description='Process cups submitted on submit.html.')
    ap.add_argument('--once', action='store_true', help='one pass (the default)')
    ap.add_argument('--loop', type=int, metavar='SECONDS', help='repeat every N seconds (development)')
    ap.add_argument('--dry-run', action='store_true', help='download and decide, print the commands, change nothing')
    ap.add_argument('--repo', help='repo to run new_cup.py in (default: this folder)')
    ap.add_argument('--worker', help='override worker_url')
    ap.add_argument('--id', help='only handle this submission id')
    ap.add_argument('--no-git', action='store_true', help='skip git fetch / publish detection')
    ap.add_argument('--reindex', action='store_true', help='ask the Worker to rebuild its index first')
    ap.add_argument('--rehearsal', action='store_true',
                    help='set COTD_SKIP_EXTERNAL=1 so new_cup.py leaves other repos and the backup drive alone')
    ap.add_argument('-v', '--verbose', action='store_true')
    args = ap.parse_args()

    ctx = Ctx(args)
    setup_logging(ctx.subdir, args.verbose)
    if args.rehearsal and os.path.isdir(os.path.join(ctx.repo, '.git')):
        log.warning('--rehearsal in a git checkout (%s): out-of-repo steps are skipped, but the cup is still '
                    'processed in this repo', ctx.repo)

    if args.loop:
        while True:
            one_pass(ctx, args)
            time.sleep(args.loop)
    rc = one_pass(ctx, args)
    sys.exit(rc)


if __name__ == '__main__':
    main()
