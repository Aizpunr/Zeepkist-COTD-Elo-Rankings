# Cups worth reconstructing

Leads, not data. Nothing here is on the site, because a "sweep missed by one
round" needs the whole cup to prove: you have to show the winner led every
OTHER round, not just identify the one they lost. A screenshot of the losing
round alone cannot do that.

To promote one of these, transcribe it into a `cotd_N.json` here like any
other reconstruction and let `build_rounds.py` work out the numbers.

## Near misses found by Kernkob (Discord, 2026-09-20)

He went through old VODs looking for sweeps. All five winners confirmed
against `cups.json`; the player named in each beat him in that round.

| cup | date | winner | lost round | to | margin | notes |
|---|---|---|---|---|---|---|
| 28 | 2023-10-07 | Kernkob | R5 | Sandals | 0.050 | would have been the **first ever sweep**, 9 cups before ZOMAN's 37 |
| 53 | 2024-06-29 | Kernkob | R6 | Renergy | 0.298 | Kernkob 43.854 to Renergy 43.556, 15 players in, top 12 advanced |
| 54 | 2024-07-06 | Kernkob | R7 | jandje | 0.055 | 46.513 to 46.458, 10 players in, top 8 advanced |
| 73 | 2024-12-14 | Kernkob | R9 | Quickracer10 | unknown | see below |
| 99 | 2025-06-28 | Kernkob | R7 | Lexer | 0.045 | 46.012 to 45.967, 22 players in, top 18 advanced |

**Cup 73's margin is not 0.065.** That figure is the gap between Quickracer10
(42.836) and Hydro (42.901), the top two of that round. Kernkob is below the
visible crop, so his actual margin is larger and unknown.

None of these would displace COTD 138 at the top of "nearly swept it", which
gave up a single round by **0.003**. Cup 99 at 0.045 and cup 28 at 0.050 would
be the next tightest if confirmed.

## Why this is slow

There is no automatic route. These cups predate the mod log entirely, so the
only sources are VOD screenshots and Lexer's workbook, and the workbook records
who went OUT each round, never who led it. Every one of them is a manual pass.

## Done since

The seven historic sweeps in `sweeps_manual.json` now carry round counts, read
straight from the elimination records: the last round anybody went out in is
the final. That agrees with the mod log on all 28 cups where both exist, so
`build_rounds.py` fills any manual sweep this way. It refuses when nobody in a
block went out in round 1, which is what a block numbered from the discovery
round looks like.
