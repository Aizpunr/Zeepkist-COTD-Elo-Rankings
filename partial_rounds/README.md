# Manual round-by-round reconstructions

For a cup with no saved mod log, this is the fallback: leaderboard screenshots
transcribed round by round. One file per cup, `cotd_N.json`, deliberately bare
so transcribing a screenshot is one paste and nothing else:

```json
{
  "cup": 135,
  "rounds": {
    "1": [["justMaki", 42.849], ["ZOMAN", 43.085], ["wokonbike", "DNF"]]
  }
}
```

| field | what |
|---|---|
| `cup` | the cup number |
| `rounds` | round number -> the rows on screen, `[raw in-game name, time]`, any order |
| `source` | where the screenshots came from |
| `complete` | `true` only when every round is transcribed (see below) |
| `aliases` | raw in-game name -> the name the rankings use, for ghost accounts |
| `notes` | free text, for whatever a future reader needs to know |

A time is seconds as a number, `"DNF"`, or `null` when the row was on screen
without one. A row with an empty name is ignored, which is how an illegible
row gets left out without inventing a name for it.

**A round's rows are not the full field the way a real log's block is.** They
are only as wide as the screenshot: sometimes the top 16, sometimes top 5 plus
bottom 5, once a podium photo. Never read an absence from a round as proof a
player did not race it.

## A half-finished file must never reach the site

With only some rounds transcribed, "the winner led every round" is trivially
true for whatever is there, which would invent a clean sweep that never
happened. So `build_rounds.py` refuses to publish a cup until it is finished,
and it prefers evidence over the file's own say-so, in this order:

1. **`cup_<N>.json`**, when the pipeline processed that cup: the runner-up's
   elimination round is the round count.
2. **Lexer's xlsx**, which records an Elim Round for every player of every cup
   ever run, so it can vouch for a cup the pipeline never touched (134, 138).
3. **`"complete": true`** in the file, only when neither of the above is on
   disk, which on a fresh clone is both of them since both are gitignored.

Until then it reports progress instead, e.g. *1 of 15 rounds transcribed so far*.

## Lexer's sheet also checks the transcription

The xlsx cannot say who LED a round, but it says who went OUT in each one, so
anyone it records as eliminated in round R must not still be racing later.
That catches a misread name or a round filed under the wrong number, and it is
reported without throwing the cup away.

The numbering is known to line up: all ten eliminations visible in COTD 138's
screenshots matched the sheet round for round. Be aware a cup can eliminate
nobody in round 1 (COTD 134 did), so the sheet's rounds do not always start
at 1.

## Ghost accounts

A player racing on someone else's account is recorded under the real player,
and `elo_engine`'s `ghosts` export is the authority (`COTD 135` is
`[3, 'del gaming', 'Sterben']`). Put it in `aliases` so the rounds credit the
right person. This is kept per cup rather than in `CANONICAL`, which five other
repos text-parse and which deliberately keeps ghosts separate so they can be
excluded from the season race.

Any name that is neither in the cup's published leaderboard nor aliased gets
dropped from the rounds and named in a warning, so a misread can never quietly
become a phantom player.

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
