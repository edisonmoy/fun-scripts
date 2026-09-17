# Resy sniper

Watches Resy for reservations you can't get through the normal booking
flow and books the instant a matching slot opens, then emails
confirmation. Watches multiple independent reservations at once - see
"Managing targets" below.

## How it works

Resy has no public API - there's no official "search availability" or
"confirm booking" integration for third parties. This talks directly to
`api.resy.com`, the same private endpoints Resy's own web/mobile clients
use, authenticated with **your** logged-in session credentials.

- `resy_api.py` - the API client (venue lookup, slot search, book-token
  fetch, book, payment method lookup).
- `targets.json` - the list of reservations to snipe. Each entry: a
  venue, a free-text description of what you want (date/time flexibility
  and all), and enabled/dry-run flags. **This is what you edit to manage
  what's being watched** - see "Managing targets" below.
- `targets.py` - loads and validates `targets.json`.
- `request_parser.py` - turns each target's free-text `request` into
  structured search criteria (party size, days of week, time window,
  lookahead) via the Claude API, once per target at startup.
- `main.py` - the poll loop: round-robins over every active target,
  checking its candidate dates, and the moment a matching slot appears,
  grabs a book token and books it. A target drops out of the loop once
  booked or disabled; others keep going.
- `alerts.py` - sends a confirmation email over Gmail SMTP once a target
  books.
- `github_sync.py` - commits a `booking` field onto the target itself in
  `targets.json` once it books. This is the single source of truth for
  booked/not-booked (not local disk, which is wiped on every redeploy) and
  is what lets [resy-sniper-web](../resy-sniper-web) display status.

## ⚠️ Read this before running it live

This isn't an official integration - it's calling Resy's internal API the
way their own frontend does, using your session token. That's outside what
Resy's Terms of Service contemplate for third-party tools, and a bot
hammering their API on a tight poll loop is exactly the kind of traffic
pattern that gets accounts flagged or rate-limited. Concretely:

- Keep `RESY_POLL_INTERVAL_SECONDS` reasonable (default 2s + jitter) rather
  than pushing it near-zero.
- Leave `RESY_DRY_RUN=true` (the default) until you've verified venue
  resolution and slot matching against real responses in the logs - it
  changes nothing about live searching, it only gates the final `/3/book`
  call.
- If your account gets flagged, this is on you - I can't tell you it's
  risk-free, only that it's a known, common risk with this class of tool
  and it's your call to accept it for your own account.
- Poll cadence (`RESY_POLL_INTERVAL_SECONDS`) is for one full round over
  **all** active targets combined, not per target - adding more targets
  doesn't multiply total Resy traffic, it just slows down how often any
  one target gets re-checked.

## Managing targets

`targets.json` is the list of reservations being watched - it's plain
data (no secrets), checked into git. The easiest way to manage it is the
password-gated dashboard at [resy-sniper-web](../resy-sniper-web)
(resy.edisonmoy.com) - add/edit/remove targets, validate that a venue name
resolves correctly and a request parses the way you'd expect, and cancel
a booked reservation, all from the browser. Saving there commits directly
to this file and redeploys the bot the same way editing it by hand would.

Each entry:

```json
{
  "key": "pizza4ps-brooklyn-saturday",
  "venue_name": "Pizza 4P's Brooklyn",
  "venue_id": 98384,
  "request": "A Saturday dinner reservation for 2, flexible on time between 5pm and 9pm. No date flexibility beyond Saturdays. Look up to 8 weeks out.",
  "enabled": true,
  "dry_run": null
}
```

| Field | Required | What |
| --- | --- | --- |
| `key` | yes | Short unique slug - namespaces this target's state, shows up in logs/emails |
| `venue_name` | yes | Search query used if `venue_id` isn't set |
| `venue_id` | no | Pin the exact venue once you've verified the search resolved correctly |
| `request` | yes | Free-text description, including party size - see "How requests are parsed" below |
| `enabled` | no (default `true`) | Set `false` to pause without deleting the target |
| `dry_run` | no (default: falls back to `RESY_DRY_RUN`) | `true` = **notify mode** (email on a match, don't book), `false` = **book mode**. The dashboard shows these as a Notify/Book toggle. |
| `booking` | no | Set automatically by `github_sync.py` once this target books - `{day, time, party_size, reservation_id}`. Never set this by hand. |

**To add, pause, or remove a target:** use the dashboard above, or edit
`targets.json` directly and redeploy (`fly deploy`) - or just tell me
(Claude) what you want watched and I'll do both. A target that's fully
booked drops out of the poll loop automatically; the process keeps
running (idle) for any others still active, and picks up newly-added or
re-enabled targets on the next restart/redeploy.

## 1. Get your Resy credentials (you're here)

Two values, both from your own logged-in browser session - there's no
"create an API key" flow, this is literally sniffing the requests Resy's
website already sends when you use it normally:

1. Open **resy.com** in Chrome and log in.
2. Open DevTools (Cmd+Option+I) → **Network** tab. Leave DevTools open.
3. Do something that hits the API - e.g. search for "Pizza 4P's" or open
   any restaurant page. You'll see a burst of requests to `api.resy.com`.
4. Click any one of those `api.resy.com` requests → **Headers** tab →
   **Request Headers**. Copy two values:
   - `x-resy-auth-token` → this is `RESY_AUTH_TOKEN`
   - `authorization` → looks like `Api-Key "abc123..."` - the part inside
     the quotes is `RESY_API_KEY`
5. Paste both into a local `.env` file (see below) - never commit this
   file, it's in `.gitignore` already.

The auth token is tied to your login session and Resy does eventually
rotate/expire it (typically when you log out or after an extended period),
so if the bot suddenly starts getting 401s, repeat this to grab a fresh
one.

```
# .env (local testing only - Fly.io deploy uses `fly secrets set` instead)
RESY_AUTH_TOKEN=paste-here
RESY_API_KEY=paste-here
RESY_PAYMENT_METHOD_ID=paste-here   # optional - see step 2b
RESY_GITHUB_TOKEN=paste-here        # fine-grained PAT, Contents: read/write on this repo
ANTHROPIC_API_KEY=paste-here
ALERT_EMAIL_FROM=your-gmail@gmail.com
ALERT_EMAIL_PASSWORD=your-gmail-app-password
ALERT_EMAIL_TO=moyedison@gmail.com
```

What to book lives in `targets.json`, not `.env` - see "Managing targets"
above.

`ALERT_EMAIL_PASSWORD` is a Gmail **app password**
(myaccount.google.com/apppasswords), not your normal login password -
Gmail SMTP rejects plain account passwords for third-party apps.

`ANTHROPIC_API_KEY` is a separate credential from this Claude Code session
- create one at console.anthropic.com/settings/keys. It's used once per
target at startup to parse that target's `request` into structured search
criteria (see "How requests are parsed" below) - small calls, well under
a cent each.

`RESY_GITHUB_TOKEN` can be the exact same token used by
[resy-sniper-web](../resy-sniper-web)'s `GITHUB_TOKEN` - same repo, same
Contents: read/write scope, used by `github_sync.py` to record a booking
back into `targets.json`.

### How requests are parsed

Rather than separate day/time-window fields, each target's `request` in
`targets.json` takes a plain-English description, e.g.:

- `"A Saturday dinner reservation for 2, flexible on time between 5pm and 9pm. No date flexibility beyond Saturdays. Look up to 8 weeks out."`
- `"Dinner for 4 any night this week, as early as we can get in"`
- `"Anniversary dinner for 2, ideally a Friday or Saturday in the next month, any time after 6pm"`

`request_parser.parse()` sends this to Claude (`claude-opus-5`) once per
target at startup and gets back structured JSON (`party_size`,
`days_of_week`, `time_window_start`/`_end`, `lookahead_weeks`, plus a
free-text `notes` field for anything it couldn't represent structurally -
e.g. "anniversary" or a specific single date). **Check the logged `notes`
field** the first time you add a new target - it's how you catch a
misparse before the bot starts polling on the wrong criteria. The
dashboard's "Check venue & request" button runs this same parse (plus
venue resolution) before you save, so you can catch a misparse - wrong
party size especially, the one field where a mistake is expensive -
without waiting for a restart.

## 2. Run it locally (dry run first)

```bash
cd resy-sniper
pip install -r requirements-dev.txt
pytest                       # unit tests, no network/credentials needed

export $(cat .env | xargs)   # or use direnv/python-dotenv, your call
python main.py                # RESY_DRY_RUN=true by default - notify mode, emails on a match, never books
```

Watch the logs. You should see each target's parsed `request` criteria
logged first (check `notes` for anything it flagged), then it resolves
each target's venue id, then round-robins over candidate dates logging
what it finds. Once you've confirmed it's matching the right
venue/criteria and correctly parsing slot times, copy each resolved venue
id into that target's `venue_id` in `targets.json` (skips a re-search
every restart), and set `RESY_DRY_RUN=false` to let it actually book when
a slot appears.

### 2b. Payment method (for venues that require a deposit)

Some venues 402 on booking with no card on file. The bot resolves your
account's default saved card automatically via a read-only lookup - to
check what it'll use, or to pin a specific card:

```bash
python -c "
from dotenv import load_dotenv; load_dotenv('.env')
import resy_api
print(resy_api.get_default_payment_method_id())
"
```

Copy the printed id into `RESY_PAYMENT_METHOD_ID` if you want to pin it
(skips the lookup every restart) or use a non-default card.

## 3. Deploy to Fly.io (always-on polling)

```bash
fly launch --no-deploy   # picks up fly.toml, creates the app, skip the first auto-deploy
fly secrets set \
  RESY_AUTH_TOKEN=... \
  RESY_API_KEY=... \
  RESY_PAYMENT_METHOD_ID=... \
  RESY_GITHUB_TOKEN=... \
  ANTHROPIC_API_KEY=... \
  ALERT_EMAIL_FROM=... \
  ALERT_EMAIL_PASSWORD=... \
  ALERT_EMAIL_TO=moyedison@gmail.com \
  RESY_DRY_RUN=false
fly deploy
fly logs   # confirm it's polling
```

`fly.toml` runs it as a plain worker process (no HTTP port, nothing to
health-check) with `restart = always` so a crash just resumes polling.
`targets.json` ships inside the image (it's committed, not a secret), so
adding/pausing a target means editing it and running `fly deploy` again.

Once every active target is booked, `main.py` stops polling and idles
instead of exiting, so Fly's `restart = always` doesn't spin the machine
into an exit/restart loop. Add a new target (or re-enable a paused one)
and redeploy to pick up watching it again; `fly apps destroy <app>` (or
scale to 0 machines) once you're done with all of them.

## Config reference

What to watch lives in `targets.json` (see "Managing targets" above) -
these env vars are global/shared settings:

| Var | Default | What |
| --- | --- | --- |
| `RESY_DRY_RUN` | `true` | Global default; set `false` to let it actually book. Per-target `dry_run` overrides this. |
| `RESY_PAYMENT_METHOD_ID` | _(resolved at startup)_ | Card to book with, shared across all targets - see step 2b |
| `RESY_POLL_INTERVAL_SECONDS` / `RESY_POLL_JITTER_SECONDS` | `2` / `0.5` | Poll cadence for one round over all active targets combined |
| `RESY_AUTH_TOKEN` / `RESY_API_KEY` | _(required)_ | From DevTools, see above |
| `RESY_GITHUB_TOKEN` | _(required)_ | Fine-grained PAT, Contents: read/write on this repo - records bookings back into `targets.json` |
| `ANTHROPIC_API_KEY` | _(required)_ | For parsing each target's `request` - console.anthropic.com/settings/keys |
| `ALERT_EMAIL_FROM` / `ALERT_EMAIL_PASSWORD` / `ALERT_EMAIL_TO` | _(required)_ | Gmail SMTP for confirmation emails |

## Known limitations

- Resy's API isn't documented, so field names in `resy_api.py`
  (`config.token`, `book_token.value`, etc.) are reverse-engineered from
  the reference implementations this was based on, not exhaustively
  confirmed against live traffic - the dry-run log output is how you
  verify a new target before trusting it to book for real.
- One payment method for every target - if you ever want different
  targets charged to different cards, `RESY_PAYMENT_METHOD_ID` would need
  to become a per-target field instead of a global setting.
- `resy_token` (the string `/3/book` and `/3/user/reservations` both
  return) rotates - the one captured at booking time no longer matched
  what `/3/user/reservations` returned minutes later (confirmed live). The
  stable identifier is `reservation_id` (a small int), which is what gets
  stored in `booking` and what the cancel flow re-looks-up a fresh
  `resy_token` from right before calling `/3/cancel` - never trust a
  stored `resy_token`.
- Resy's `/4/find` can fail with a 500 on every single request for one
  venue for several minutes straight while unrelated one-off requests
  from a different source succeed the whole time (confirmed live) - looks
  like either venue-specific flakiness or the polling IP getting
  soft-throttled under sustained load, and there's no way to tell which
  from here. `main.py` backs off exponentially (2x per consecutive
  all-dates-failed round, capped at 30x) while this persists, resetting
  the moment a round comes back clean, so a sustained bad stretch doesn't
  turn into sustained hammering.
- After some Fly deploys, a machine gets stuck in `stopped` right after
  "Configuring firecracker" and never proceeds to actually running
  `main.py`, even though the deploy itself reports success (confirmed
  live, several times, always resolved by `fly machine start <id>`).
  Looks like a Fly platform quirk with this app's rolling-deploy +
  standby-machine setup, not anything in the code - if `fly status` shows
  `stopped` a while after a deploy finished, that's the fix.
