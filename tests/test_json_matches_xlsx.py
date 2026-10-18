"""cup_N.json and the results/ Elim Time column must carry the same values.

Both are written from cotd_parser.time_to_ms(), so any drift means one of
the writers stopped using it. results/ is the tracked copy of the workbooks
(results_store.py), so this runs everywhere.
"""
import glob
import json
import os

import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _workbook_path():
    import elo_engine
    return elo_engine.XLSX_FILES[-1]


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
    import results_store
    with open(os.path.join(fixture_dir, 'expected.json'), encoding='utf-8') as f:
        expected = json.load(f)
    wb = results_store.load_workbook(path)
    block = _xlsx_block(wb, expected['cup'])
    if block is None:
        pytest.skip(f"{expected['cup']} is not in {os.path.basename(path)}")
    want = {p['name']: p['time'] for p in expected['players']}
    assert block == want
