"""cup_paths.py: where the per-cup files live.

The pipeline writes two files per cup, and for 160-odd cups they had piled up
loose in the repo root. They now live under cup_data/, and every producer and
consumer asks this module for the path rather than building it themselves, so
moving them again is a one line change here instead of a hunt through seven
files.

  cup_data/cup_<N>.json                     the finished leaderboard
  cup_data/ltg_reports/cotd_<N>_ltg_report.json   the Left The Game audit trail

cup_data/ is served as part of the site: lexertools.html fetches a cup file by
URL, so the folder name must stay URL safe (no spaces) and must not be added to
.gitignore.
"""
import glob
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))

CUP_DATA_DIR = 'cup_data'
LTG_REPORT_DIR = os.path.join(CUP_DATA_DIR, 'ltg_reports')

# What lexertools.html prefixes its fetch with. Kept next to the constant it
# has to agree with, so the two cannot drift apart silently.
WEB_CUP_DATA_DIR = 'cup_data'


def cup_dir(base=BASE):
    return os.path.join(base, CUP_DATA_DIR)


def cup_json_path(num, base=BASE):
    """Absolute path of cup_<num>.json, whether or not it exists yet."""
    return os.path.join(base, CUP_DATA_DIR, f'cup_{num}.json')


def ltg_report_path(num, base=BASE):
    return os.path.join(base, LTG_REPORT_DIR, f'cotd_{num}_ltg_report.json')


def all_cup_json(base=BASE):
    """Every cup_<N>.json, sorted by cup number.

    The glob is cup_[0-9]*.json on purpose: cup_*.json would also match
    cup_meta.json, which is a different thing entirely.
    """
    paths = glob.glob(os.path.join(base, CUP_DATA_DIR, 'cup_[0-9]*.json'))
    return sorted(paths, key=lambda p: int(re.search(r'cup_(\d+)\.json$', p).group(1)))


def ensure_dirs(base=BASE):
    """Make the folders if they are missing. Safe to call every run."""
    os.makedirs(os.path.join(base, LTG_REPORT_DIR), exist_ok=True)
