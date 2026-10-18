"""results_store.py: the cup results, kept as tracked JSON under results/.

The result workbooks used to be the source of truth. They were gitignored, so
only the operator's PC could rebuild the site. The same cells now live here:

  results/books.json            the books in reader order: id, xlsx filename,
                                kind, and each sheet's name and dimensions
  results/cups/<slug>.json      one file per result block (a 'Position' header
                                and the four columns under and above it)
  results/sheets/<book>/<n>.json  every other non-empty cell of a sheet

load_workbook() rebuilds a sheet cell for cell from those files and hands back
an object with the slice of the openpyxl API the readers use, so every reader
keeps its exact parsing rules. The xlsx files are a backup that sync_xlsx.py
regenerates from here.

A block file is meant to be edited by hand (ghost tags, ties, removals):
'rows' is one list per spreadsheet row, [Position, Name, Elim Time, Elim
Round], with null for an empty cell. A null Position means "tied with the row
above", exactly as in the workbook. COTD 131 and 132 exist twice; the engine
keeps the first in reader order, cotd-131.json / cotd-132.json, and the
'-also-in-' copies are the current book's leftovers.
"""
import glob
import json
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = 'results'
BLOCK_WIDTH = 4


def _root(base):
    return os.path.join(base or BASE, RESULTS_DIR)


def _read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def slugify(text):
    s = re.sub(r'[^0-9A-Za-z]+', '-', str(text)).strip('-').lower()
    return s or 'x'


def dump_block(block):
    """Block JSON with one spreadsheet row per line, so diffs read like the sheet."""
    out = ['{']
    keys = list(block)
    for i, k in enumerate(keys):
        comma = ',' if i < len(keys) - 1 else ''
        v = block[k]
        if k in ('above', 'rows'):
            if not v:
                out.append(f'  {json.dumps(k)}: []{comma}')
                continue
            out.append(f'  {json.dumps(k)}: [')
            for j, row in enumerate(v):
                rc = ',' if j < len(v) - 1 else ''
                out.append('    ' + json.dumps(row, ensure_ascii=False) + rc)
            out.append(f'  ]{comma}')
        else:
            out.append(f'  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}{comma}')
    out.append('}')
    return '\n'.join(out) + '\n'


def dump_sheet(sheet):
    out = ['{', f'  "cells": [']
    cells = sheet['cells']
    for j, cell in enumerate(cells):
        rc = ',' if j < len(cells) - 1 else ''
        out.append('    ' + json.dumps(cell, ensure_ascii=False) + rc)
    out.append('  ]')
    out.append('}')
    return '\n'.join(out) + '\n'


def dump_books(books):
    return json.dumps(books, ensure_ascii=False, indent=2) + '\n'


def sheet_file(book_id, sheet_index, base=None):
    return os.path.join(_root(base), 'sheets', book_id, f'{sheet_index:02d}.json')


# ------------------------------------------------------------------ reading

_CACHE = {}


def books(base=None):
    return _read_json(os.path.join(_root(base), 'books.json'))


def book_files(kind, base=None):
    """xlsx filenames of one kind ('cotd', 'roulette', 'troll', 'lexer'), in order."""
    return [b['xlsx'] for b in books(base) if b['kind'] == kind]


def read_block(path):
    return _read_json(path)


def blocks(base=None):
    """{slug: block} for every results/cups/*.json."""
    out = {}
    for path in sorted(glob.glob(os.path.join(_root(base), 'cups', '*.json'))):
        out[os.path.splitext(os.path.basename(path))[0]] = _read_json(path)
    return out


def block_cells(block):
    """{(row, col): value} for the non-empty cells of a block."""
    col, hr = block['col'], block['header_row']
    cells = {}
    rows = [(1 + i, r) for i, r in enumerate(block['above'])]
    rows.append((hr, block['header']))
    rows += [(hr + 1 + i, r) for i, r in enumerate(block['rows'])]
    for r, vals in rows:
        for j, v in enumerate(vals):
            if v is not None:
                cells[(r, col + j)] = v
    return cells


class _Cell:
    __slots__ = ('value',)

    def __init__(self, value):
        self.value = value


class Sheet:
    def __init__(self, title, max_row, max_column, cells):
        self.title = title
        self.max_row = max_row
        self.max_column = max_column
        self._cells = cells

    def cell(self, row, column, value=None):
        if value is not None:
            raise TypeError('results_store sheets are read-only')
        return _Cell(self._cells.get((row, column)))

    def iter_rows(self, values_only=False):
        if not values_only:
            raise TypeError('results_store sheets only support values_only=True')
        get = self._cells.get
        cols = range(1, self.max_column + 1)
        for r in range(1, self.max_row + 1):
            yield tuple(get((r, c)) for c in cols)


class Workbook:
    def __init__(self, sheets):
        self.worksheets = sheets
        self.sheetnames = [s.title for s in sheets]

    def __getitem__(self, name):
        return self.worksheets[self.sheetnames.index(name)]

    def close(self):
        pass


def load_workbook(path, data_only=True, read_only=False, base=None):
    """Stand-in for openpyxl.load_workbook over results/, keyed by xlsx filename."""
    name = os.path.basename(path)
    key = (os.path.abspath(_root(base)), name)
    if key in _CACHE:
        return _CACHE[key]
    book = next((b for b in books(base) if b['xlsx'] == name), None)
    if book is None:
        raise FileNotFoundError(path)
    by_sheet = {}
    for blk in blocks(base).values():
        if blk['book'] == book['id']:
            by_sheet.setdefault(blk['sheet'], {}).update(block_cells(blk))
    sheets = []
    for i, sh in enumerate(book['sheets']):
        cells = {}
        sp = sheet_file(book['id'], i, base)
        if os.path.exists(sp):
            for r, c, v in _read_json(sp)['cells']:
                cells[(r, c)] = v
        for rc, v in by_sheet.get(sh['name'], {}).items():
            if rc in cells:
                raise ValueError(f'{name} / {sh["name"]}: cell {rc} is in a block and in the sheet file')
            cells[rc] = v
        sheets.append(Sheet(sh['name'], sh['max_row'], sh['max_column'], cells))
    wb = Workbook(sheets)
    _CACHE[key] = wb
    return wb


def clear_cache():
    _CACHE.clear()


# ------------------------------------------------------------------ writing

def cup_slug(cup_id):
    return slugify(cup_id)


def add_cup_block(cup_id, map_line, fastest_line, rows, base=None):
    """Append a new COTD block to the last 'cotd' book, laid out as new_cup.py
    always wrote it into the workbook: first sheet, 6 columns right of the last
    Position header, title on row 2, map on row 3, fastest on row 4 (third
    column), header on row 5. Returns the block's path."""
    root = _root(base)
    bks = books(base)
    book = [b for b in bks if b['kind'] == 'cotd'][-1]
    sheet = book['sheets'][0]
    existing = [b for b in blocks(base).values()
                if b['book'] == book['id'] and b['sheet'] == sheet['name']]
    last_col = max(b['col'] for b in existing if b['header_row'] == 5)
    col = last_col + 6
    above = [[None] * BLOCK_WIDTH for _ in range(4)]
    above[1][0] = cup_id
    above[2][0] = map_line
    if fastest_line is not None:
        above[3][2] = fastest_line
    block = {
        'book': book['id'], 'sheet': sheet['name'], 'col': col, 'header_row': 5,
        'above': above,
        'header': ['Position', 'Name', 'Elim Time', 'Elim Round'],
        'rows': [list(r) for r in rows],
    }
    path = os.path.join(root, 'cups', cup_slug(cup_id) + '.json')
    if os.path.exists(path):
        raise FileExistsError(path)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(dump_block(block))
    sheet['max_column'] = max(sheet['max_column'], col + BLOCK_WIDTH - 1)
    sheet['max_row'] = max(sheet['max_row'], 5 + len(rows))
    m = re.fullmatch(r'COTD (\d+)-(\d+)\.xlsx', book['xlsx'])
    n = re.search(r'\d+', cup_id)
    if m and n and int(n.group()) > int(m.group(2)):
        book['xlsx'] = f'COTD {m.group(1)}-{n.group()}.xlsx'
    write_books(bks, base)
    return path


def write_books(bks, base=None):
    with open(os.path.join(_root(base), 'books.json'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(dump_books(bks))
    clear_cache()


def cotd_ids(base=None):
    """Every block title in the 'cotd' books (e.g. 'COTD 164')."""
    ids = set()
    cotd_books = {b['id'] for b in books(base) if b['kind'] == 'cotd'}
    for blk in blocks(base).values():
        if blk['book'] in cotd_books:
            for row in blk['above']:
                v = row[0]
                if isinstance(v, str) and v.strip().startswith(('COTD', 'COTW')):
                    ids.add(v.strip())
    return ids
