"""Contract tests for elo_engine as an importable module.

Importing elo_engine must be cheap and silent (scripts in this repo and in
sibling repos do `from elo_engine import CANONICAL`), CANONICAL must remain
a top-level dict literal that the older text-parsing readers in other repos
can still extract, and the current workbook filename must appear exactly
once as a quoted literal because new_cup.py rewrites it by string replace.
"""
import ast
import importlib
import os
import re
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
ENGINE_PATH = os.path.join(REPO, 'elo_engine.py')


@pytest.fixture(scope='module')
def engine_source():
    with open(ENGINE_PATH, encoding='utf-8') as f:
        return f.read()


def test_import_is_silent_and_leaves_stdout_alone(capsys):
    sys.modules.pop('elo_engine', None)
    enc_before = sys.stdout.encoding
    mod = importlib.import_module('elo_engine')
    out, err = capsys.readouterr()
    assert out == '' and err == '', 'importing elo_engine printed something'
    assert sys.stdout.encoding == enc_before
    assert isinstance(mod.CANONICAL, dict) and len(mod.CANONICAL) > 100
    assert callable(mod.main)


def test_xlsx_literal_is_unique_and_well_formed(engine_source):
    import elo_engine
    last = elo_engine.XLSX_FILES[-1]
    assert re.fullmatch(r'COTD \d+-\d+\.xlsx', last)
    assert engine_source.count(f"'{last}'") == 1, 'new_cup.py string-replaces this literal'
    assert elo_engine.XLSX_FILES[0] == 'Zeepkist COTDs 1-25.xlsx'


def test_canonical_survives_every_external_extraction_style(engine_source):
    """The three ways sibling repos read CANONICAL out of the source text."""
    import elo_engine
    src = engine_source

    # 1. zeepkist holistic: regex + ast.literal_eval
    m = re.search(r'^CANONICAL\s*=\s*(\{.*?^\})', src, re.MULTILINE | re.DOTALL)
    assert m, 'holistic-style regex no longer matches'
    assert ast.literal_eval(m.group(1)) == elo_engine.CANONICAL

    # 2. gtr_analysis: line scanner that stops at the first bare '}'
    block, collecting = [], False
    for line in src.split('\n'):
        if not collecting and re.match(r'^CANONICAL\s*=\s*\{', line):
            collecting = True
            block.append(line.split('=', 1)[1].strip())
            continue
        if collecting:
            block.append(line)
            if line.strip() == '}':
                break
    assert ast.literal_eval('\n'.join(block)) == elo_engine.CANONICAL

    # 3. TyO / qube: AST walk for a top-level Assign with a literal dict
    found = None
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == 'CANONICAL' for t in node.targets):
            found = ast.literal_eval(node.value)
    assert found == elo_engine.CANONICAL


def test_no_duplicate_canonical_keys(engine_source):
    m = re.search(r'^CANONICAL\s*=\s*(\{.*?^\})', engine_source, re.MULTILINE | re.DOTALL)
    keys = [k.value for k in ast.parse(m.group(1), mode='eval').body.keys]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    assert dupes == [], f'duplicate CANONICAL keys: {dupes}'
