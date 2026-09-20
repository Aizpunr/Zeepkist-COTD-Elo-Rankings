# Manual round-by-round reconstructions

For a cup that has no saved mod log (COTD 138 is currently the only one —
`new_cup.py` wasn't used that week and BepInEx overwrote it before it could be
copied), this is the fallback: leaderboard screenshots shared in chat,
transcribed round by round.

One file per cup, `cotd_N.json`:

| field | what |
|---|---|
| `cup` | the cup number |
| `source` | where the screenshots came from |
| `rounds` | one entry per elimination round: `round`, `leader` (name + time — the only load-bearing field), `visible` (whatever portion of the field was on screen, raw in-game names), `field_remaining` when a player counter was visible, `eliminated_earlier` when a killfeed on screen named a prior round's casualties |

**`visible` is not a full field the way a real log's leaderboard block is.**
It is only as wide as the screenshot — sometimes the top 16, sometimes top 5
+ bottom 5, once a podium photo. Never treat an absence from `visible` as
proof a player didn't race that round.

`build_rounds.py` reads every file here and folds it into `rounds.json`
alongside the real logs, with `src: "partial"` so the page can say so. It
reuses `round_metrics()` — the same function the golden-fixture tests exercise
— by treating each round's `visible` list as that round's board, `DNF`/`null`
times mapped to unfinished. Because `visible` names are confirmed racers
(they're on the screen with a time or a DNF), feeding them into the per-player
"rounds raced" count is safe even though it's a lower bound, not exact — the
same caveat a real log's field size already carries when a livelog started
late.

## Adding one

Transcribe screenshots round by round, correcting any name that doesn't match
an existing player (check `elo_engine.CANONICAL` before trusting a blurry
read — COTD 138's round 1 was first mistranscribed as `JukeAdjacent`, which
matched no alias anywhere, before every other round confirmed it was
`JakeAdjacent`). A round only needs its **leader** to be certain; everything
else is bonus. Run `python build_rounds.py` after and check the cup's row in
the printed summary.
