# Golden fixtures for the cup log parser

Each `cotd_N/` directory is one real cup:

| file | what |
|---|---|
| `cotd_N.log` | the `COTDTracker` lines of the original `cup logs/cotd_N.log`, byte-exact (CRLF kept, see `.gitattributes`) |
| `expected.json` | the `cup_N.json` the pipeline produced from that log |
| `manifest.json` | `cup`, `mapper`, `map`, the full `exclude` set the parser was run with, `source_log`, `note` |

`tests/test_parser_golden.py` parses every fixture with its `exclude` set and
asserts the result equals `expected.json` as a dict and as serialized text.
`tests/test_json_matches_xlsx.py` additionally checks the JSON times against
the xlsx Elim Time column when the workbook is present.

## Adding a fixture

1. `python tests/discover_fixtures.py N` to see whether the cup reproduces and
   with which exclude set (it infers testers / mapper handles from the diff).
2. `python tests/make_fixture.py N --exclude "a,b" --note "why this cup"`.
   It validates in memory first and writes nothing unless the trimmed log
   reproduces `cup_N.json` exactly.

## Cups that can never be fixtures

`excluded_cups.json` lists cups whose committed `cup_N.json` was changed
after processing (left-the-game corrections, a hand relabel, or the old
tie rule), with the reason. They are documented so nobody wastes time
trying to make them reproduce.

## Coverage of the current set

- 148: dot-locale log (an attendee's PC), mapper absent from the log, 9 DNFs, ties
- 150: four excludes including two spellings of the same mapper
- 152: the `[MMM]Victor` raw-name gotcha plus a left-before-round-1 removal
- 153: 20 ties and 28 DNFs
- 154: smallest field (34 players, 14 rounds)
- 156: a second excluded name besides the mapper
- 159: dot-locale log, mapper raced under a different handle (`Fiets38`)
- 160: latest, comma-locale log, mapper present in the log

Spares that also reproduce (not committed to keep the set small): 141, 145,
146, 149, 151, 155, 157.
