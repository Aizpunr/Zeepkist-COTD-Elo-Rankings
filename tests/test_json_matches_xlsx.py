"""cup_N.json and the xlsx Elim Time column must carry the same values.

Both are written from cotd_parser.time_to_ms(), so any drift means one of
the writers stopped using it. The xlsx is gitignored, so this test skips
when the workbook is not present (CI, another machine).
"""
import glob
import json
import os

import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _workbook_path():
    import elo_engine
    path = os.path.join(REPO, elo_engine.XLSX_FILES[-1])
    return path if os.path.exists(path) else None


def _xlsx_block(wb, cup_id):
    """{name: elim_time} for one cup block, or None if the cup is not in the book."""
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        for ri, row in enumerate(rows):
            for ci, v in enumerate(row):
                if v != cup_id:
                    continue
                for pr in range(ri, min(ri + 6, len(rows))):
                    if rows[pr][ci] == 'Position':
                        out = {}
                        for rr in range(pr + 1, len(rows)):
                            name = rows[rr][ci + 1] if ci + 1 < len(rows[rr]) else None
                            if name is None:
                                # blank row = a player removed after processing
                                # (cells cleared); elo_engine.parse_file skips these too
                                continue
                            out[str(name).strip()] = rows[rr][ci + 2]
                        return out
    return None


@pytest.mark.parametrize('fixture_dir', sorted(glob.glob(os.path.join(FIXTURES, 'cotd_*'))),
                         ids=lambda d: os.path.basename(d))
def test_json_times_equal_xlsx_elim_times(fixture_dir):
    path = _workbook_path()
    if path is None:
        pytest.skip('current COTD workbook not present (gitignored)')
    import openpyxl
    with open(os.path.join(fixture_dir, 'expected.json'), encoding='utf-8') as f:
        expected = json.load(f)
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    block = _xlsx_block(wb, expected['cup'])
    if block is None:
        pytest.skip(f"{expected['cup']} is not in {os.path.basename(path)}")
    want = {p['name']: p['time'] for p in expected['players']}
    assert block == want
