# cotd-submit Worker

A Cloudflare Worker that receives cup logs from `submit.html` and hands them to the operator's PC. The PC side is `submissions_poll.py` in the repo root, which runs `new_cup.py` on each submission. Publishing stays manual.

```
submit.html  --POST /submit-->  Worker + KV  <--GET /pending, /log/<id>--  submissions_poll.py
             <--GET /status---               <--POST /status/<id>--------  (Task Scheduler, 15 min)
```

Free tier only: Workers + Workers KV need no payment card. R2 is not used.

## Storage (KV binding `SUBMISSIONS`)

| Key | Value |
|---|---|
| `log:<id>` | Raw log bytes. Metadata holds `cup`, `sha256`, `size`. |
| `sub:<id>` | The submission record (JSON). The authoritative copy. |
| `sha:<sha256>` | Id of the submission with that exact file (dedupe). |
| `index` | JSON array of records, newest first, capped at `MAX_INDEX`. |

Record fields: `id, cup, map, mapper, exclude, date, submitter, created, updated, status, size, sha256, n_blocks, preview, summary, note`. No IP address, user agent or Turnstile data is stored.

Ids look like `20260927T1409-12142fb0` (UTC minute plus 8 random hex digits).

## Endpoints

Every response is JSON except `/log/<id>`. Errors are `{"ok": false, "error": "<code>", "message": "...", "details": {...}}`, with CORS headers so the page can show the message.

| Method and path | Who | What |
|---|---|---|
| `GET /` | anyone | Health check. |
| `POST /submit` | the site (Origin allowlist + Turnstile) | Multipart: `file`, `cup`, `map`, `mapper`, `exclude` (JSON array), `date`, `submitter`, `preview` (JSON), `cf-turnstile-response`. |
| `GET /status` | anyone | Last 50 records. |
| `GET /pending` | poller | Records with status `received` or `processed`. |
| `GET /log/<id>` | poller | Log bytes, `X-Sha256` header. |
| `POST /status/<id>` | poller | `{"status", "note"?, "summary"?}`. |
| `POST /reindex` | poller | Rebuild `index` from the `sub:` records. |

Poller endpoints need `Authorization: Bearer <POLLER_TOKEN>`.

`/submit` rejects:

- files over 5 MB or without COTDTracker elimination rounds;
- cup numbers outside 100 to 999, and dates more than 60 days old;
- any value starting with `--`, or containing a line break (`new_cup.py` finds its flags by exact match in its arguments);
- excluded names containing a comma (`--exclude` is comma separated);
- more than `DAILY_SUBMIT_CAP` submissions in 24 hours.

An identical file (same SHA-256) returns the earlier id with status `duplicate` and stores nothing.

### Known limitation: the index

`index` is read, modified and written back, so two writes landing at the same moment can drop one record from it. The `sub:` records are never lost. `POST /status/<id>` puts a missing record back, and the poller calls `/reindex` once a day. With one cup a week this has not been worth a Durable Object.

## One-time setup

These steps need your Cloudflare login, so they cannot be scripted for you.

1. Create a free Cloudflare account at https://dash.cloudflare.com/sign-up. No card is needed.
2. In this folder: `npm install`, then `npx wrangler login` (opens the browser).
3. Create the KV namespaces and paste both ids into `wrangler.toml`:
   ```
   npx wrangler kv namespace create SUBMISSIONS
   npx wrangler kv namespace create SUBMISSIONS --preview
   ```
4. Dashboard, Turnstile, Add widget: name `cotd-submit`, hostnames `aizpunr.github.io` and `localhost`, mode Managed. Put the **site key** in `submit.html` (`PROD_TURNSTILE_SITE_KEY`), then store the **secret key**:
   ```
   npx wrangler secret put TURNSTILE_SECRET
   ```
5. Make a poller token and store it in the Worker and in `submit_config.json` (repo root, gitignored):
   ```
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   npx wrangler secret put POLLER_TOKEN
   ```
   ```json
   {"worker_url": "https://cotd-submit.<your-subdomain>.workers.dev", "poller_token": "<token>"}
   ```
6. `npx wrangler deploy`. Put the printed workers.dev URL in `submit.html` (`PROD_WORKER_URL`) and in `submit_config.json`.
7. Register the poller (runs as you, only while you are logged on, which the toasts need). In PowerShell (plain `schtasks /TR` quoting breaks there on the spaces in the path):
   ```
   $py = "C:\Users\rafa\AppData\Local\Programs\Python\Python310\pythonw.exe"
   $action = New-ScheduledTaskAction -Execute $py -Argument '"C:\Users\rafa\Desktop\Claude\zeepkist cotd elo\submissions_poll.py" --once' -WorkingDirectory "C:\Users\rafa\Desktop\Claude\zeepkist cotd elo"
   $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
   $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
   $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
   Register-ScheduledTask -TaskName "COTD submissions poll" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force
   ```
   The poller uses the `certifi` CA bundle when it is installed (`pip install certifi`): Python's default store on Windows can fail on workers.dev certificates with "certificate has expired".
   Then run `python submissions_poll.py --once -v` once by hand and check `cup logs/submissions/poll.log`.
8. Commit and push `submit.html` with the two values filled in.

## Day to day

| Task | Command |
|---|---|
| Local Worker (uses `.dev.vars`, simulated KV) | `npx wrangler dev --port 8787` |
| Live logs | `npx wrangler tail` |
| Deploy a change | `npx wrangler deploy` |
| Pause the poller | create `cup logs/submissions/PAUSE`; delete it to resume |
| Poller dry run | `python submissions_poll.py --once --dry-run -v` |
| Stop the scheduled task | `schtasks /Change /TN "COTD submissions poll" /DISABLE` |

`.dev.vars` (gitignored) uses Cloudflare's always-pass Turnstile test secret and `POLLER_TOKEN=devtoken`. On localhost, `submit.html` talks to `http://127.0.0.1:8787` with the matching test site key.

## Rotating the poller token

Generate a new token, run `npx wrangler secret put POLLER_TOKEN`, and update `submit_config.json`. The next poller pass uses it.

## Free tier limits that matter

- 1,000 KV writes per day. A submission costs 4 writes and a status change costs 2.
- 1,000 KV list operations per day. Only `/reindex` lists, once a day.
- 25 MB per KV value. Logs are capped at 5 MB and are usually under 0.5 MB.
- 100,000 Worker requests per day.
