# Root tidy, 2026-09-21

The repo root had grown to 145 files. These 22 were moved here, not deleted.
Nothing in the tree referenced any of them, which was checked by searching every
.py, .html, .md, .json and .txt in the repo for each filename first.

| folder | what |
|---|---|
| `pipeline runs/` | saved console output of `new_cup.py` runs for cups 147, 149, 151, 152 |
| `video experiment/` | the COTD 150 chart race: preview clip, two upscaler comparison crops, render log. The DATA it was built from stays in the root, because `render_elo_video.py` still reads it |
| `top5 runs 141/` | a one-off plot of the top 5 runs of COTD 141 |
| `old pages/` | superseded copies of index.html and an unfinished big3 page |
| `stray output/` | odds and ends: a steam_ids backup, server and scratch logs, an old elo simulation, an unrelated text file |

## The oddly named file

`stray output/C?tmpcup_dates_dict.txt` is a bug artifact. Something tried to
write to `C:	mp\cup_dates_dict.txt`, and because a colon cannot appear in a
Windows filename it was substituted with U+F03A, a private use character that
looks like one. The result was a file NAMED like a path, created in the repo
root instead of in C:	mp. Worth remembering if a script ever writes to an
absolute path again and the file seems to vanish.

## Deliberately left in the root

`elo_history_weighted*.csv/json` and `elo_sim.py` look like experiment leftovers
but are not: the first are inputs to `render_elo_video.py`, and the second is
imported by `elo_stability.py`.
