# Submitting a COTD cup

If you played a Cup of the Day, your game log holds every round of it. You can send that log from the rankings site and it gets turned into rating updates without anyone typing results by hand.

Page: https://aizpunr.github.io/Zeepkist-COTD-Elo-Rankings/submit.html (also the "Submit cup" button on the rankings).

## 1. Get your log

The file is:

```
C:\Program Files (x86)\Steam\steamapps\common\Zeepkist\BepInEx\LogOutput.log
```

Zeepkist overwrites it every time the game starts. Copy it somewhere safe **before** you launch the game again. It only contains cup rounds if the COTD tracker mod was running for you during the cup.

If you left the cup early, your log stops when you left. A log from someone who stayed until the final is better, but send yours anyway: when several logs arrive for one cup, the most complete one is used automatically.

## 2. Drop it on the page and check the result

The page reads the file in your browser. Nothing is uploaded until you press Submit. You will see the winner, the podium, the number of players and rounds, and the full leaderboard. Compare it with what you saw in game.

Fill in:

- **Cup number.** Filled in for you as the next cup after the last one on the site.
- **Date.** The day the cup was played. Defaults to the most recent Saturday.
- **Map name.** As announced.
- **Mapper.** Their exact in-game name, clan tag included (for example `[MMM]Victor`, not `Victor`). If the mapper raced, pick them from the list; usually they did not, so type the name. The mapper never counts as a player.
- **Also exclude.** Only people who were in the lobby but did not race: testers, or someone who left before round 1 started. Anyone who raced at least one round stays in, even if they quit.

If the page says there is **no single winner**, someone disconnected in a way the tracker never eliminated, or the log stops before the final. If a name in that list left early, tick it under "Also exclude". If your log is cut short, it cannot be used on its own.

## 3. Send it

Complete the anti-bot check and press Submit. The "Recent submissions" table shows what happens next:

| Status | Meaning |
|---|---|
| received | Waiting to be picked up. aizpun's PC checks about every 15 minutes while it is on. |
| processed | Ratings computed. aizpun checks the result, then publishes it. |
| published | Live on the rankings. |
| duplicate | That cup was already processed, or this exact file was already sent. |
| superseded | A more complete log for the same cup was sent. |
| failed | The pipeline stopped; the note says why. Ping aizpun. |

## Privacy

The log is a game log. Besides cup rounds it contains in-game names and the mods you run. It is stored only so it can be processed and kept as the raw record of the cup. No IP address is stored with a submission.
