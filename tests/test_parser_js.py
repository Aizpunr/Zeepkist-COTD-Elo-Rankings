"""Run the JavaScript parser port's tests from pytest.

cotd_parser.js (used by submit.html to preview a log in the browser) must
agree byte for byte with cotd_parser.py. The checks live in tests/js/ and
run under Node; this wrapper makes `python -m pytest tests -q` cover them.
Skipped when Node is not installed.
"""
import os
import shutil
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which('node')

pytestmark = pytest.mark.skipif(NODE is None, reason='node not installed')


def _run(args):
    r = subprocess.run([NODE] + args, cwd=REPO, capture_output=True,
                       encoding='utf-8', errors='replace', timeout=120)
    return r.returncode, r.stdout + r.stderr


def test_js_parser_matches_every_golden_fixture():
    rc, out = _run([os.path.join('tests', 'js', 'run_fixtures.mjs')])
    assert rc == 0, out


def test_js_parser_rules():
    rc, out = _run(['--test', os.path.join('tests', 'js', 'test_rules.mjs')])
    assert rc == 0, out
