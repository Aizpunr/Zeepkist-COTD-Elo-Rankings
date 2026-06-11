Retired one-off / superseded scripts. Kept for reference, NOT part of the pipeline.

- rising.py           superseded: elo_engine.py builds rising.json now. Running this
                      would clobber rising.json with an old schema (no lookback_3m)
                      and break the next build_altrank.py run.
- parse_cup.py        one-off (cup 134), hardcoded, no encoding arg.
- write_cup134.py     one-off (cup 134).
- fix_dnf_display.py  one-off DNF patch, points at COTD 131-140.xlsx (gone).
- build_cups_backup.py old copy of build_cups.py, references a deleted xlsx.
