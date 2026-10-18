"""results/ and the xlsx backups must hold the same cells.

results/ is the source; the workbooks are regenerated from it by sync_xlsx.py.
Skips when the workbooks are not on disk (they are gitignored).
"""
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_every_sheet_matches_its_workbook():
    import results_store
    missing = [b['xlsx'] for b in results_store.books()
               if not os.path.exists(os.path.join(REPO, b['xlsx']))]
    if missing:
        pytest.skip(f'xlsx backups not present: {", ".join(missing)}')
    import export_results
    assert export_results.audit(REPO) == 0, 'run python sync_xlsx.py'
