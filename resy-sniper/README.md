# resy-sniper

Polls Resy for a table at a target restaurant and books it automatically
when a slot matching your preferences appears, then emails you the details.

Preconfigured target: **Pizza 4P's Brooklyn (Greenpoint)**, table for 2,
Saturdays, dinner preferred (6–9pm) but will accept 5–10pm.

## Read this first: this is against Resy's Terms of Service

This talks to `api.resy.com`, Resy's **private, undocumented API**, using an
auth token lifted from your own browser session. It is not an official or
partner integration, and there is no Resy API program that sanctions it.

Resy's Terms of Use prohibit accessing the service by automated means —
bots, scrapers, and scripted booking all fall under that. Concretely:

- **Your Resy account can be suspended or banned**, which also kills any
  existing reservations on it.
- **Restaurants can blacklist you** for bot bookings; some actively watch
  for this.
- **Resy can change or block the API at any time**, with no notice and no
  deprecation window. Endpoints here were reverse-engineered from other
  people's captures and may already be stale.
- Repeated no-shows or cancellations from sniped reservations are what
  restaurants actually object to — if you book, go or cancel early.

This tool doesn't reduce any of that risk; it's a personal-use script that
takes an action you could take by hand, faster. Deciding that trade is
worth it is your call, but make it knowingly. The polite-usage defaults
(request throttling, browser-like headers, stopping after one booking)
are about not making things worse, not about making this permitted.

## What it will and won't do on its own

Auto-booking spends real money and reputation, so the defaults are
conservative:

| Guard | Default | Override |
| --- | --- | --- |
| Booking for real | **off** — dry run only, logs and emails what it *would* book | `RESY_LIVE_BOOKING=1` |
| Slots with a cancellation fee | **refused** | `RESY_MAX_CANCELLATION_FEE=25` |
| Bar/counter stools | **skipped** (you asked for a table) | `RESY_ALLOW_BAR=1` |
| Double-booking the same night | blocked by checking your existing reservations | — |
| Request rate | 0.5s between every API call | `RESY_MIN_REQUEST_INTERVAL` |

It stops after the first successful booking. It will never book more than
one table per run.

## Setup

### 1. Credentials

Both come from DevTools on a logged-in `resy.com` tab: open Network, click
any `api.resy.com` request, read the request headers.

- `RESY_API_KEY` — from `Authorization: ResyAPI api_key="..."`
- `RESY_AUTH_TOKEN` — from `X-Resy-Auth-Token`

```bash
cp .env.example .env   # .env is gitignored; never commit real values
```

**The auth token expires after roughly 45 days.** When it does, every call
starts returning 401 and the sniper stops working — it doesn't self-renew.
`AuthError` says exactly this in the logs. Plan on re-pasting the token
every month or so.

### 2. Resolve the venue ID

Resy venue IDs aren't published anywhere, so look it up once:

```bash
pip install -r requirements.txt
python cli.py find-venue "Pizza 4P's"
```

Put the number in `RESY_VENUE_ID`.

### 3. Email

Uses Gmail SMTP with an [app password](https://myaccount.google.com/apppasswords)
(requires 2FA on the account) — the same pattern as `concert-ticket-alerts/`
in this repo. Set `ALERT_EMAIL_FROM`, `ALERT_EMAIL_PASSWORD`, `ALERT_EMAIL_TO`.

This deliberately does **not** use the Gmail MCP connector: MCP tools only
exist inside a Claude session, and this service has to be able to email you
from Vercel or Fly at 9am on a Saturday with nobody watching. Resy also
sends its own confirmation email — this one just arrives sooner.

## Running it

```bash
python cli.py check                  # show availability, book nothing
python cli.py run                    # one pass (dry run unless RESY_LIVE_BOOKING=1)
python cli.py run --live             # one pass, will really book
python cli.py watch --interval 30    # poll until something books
python cli.py watch --interval 2 --max-minutes 10 --live   # drop-time snipe
```

Start with `check`, then `run` (dry), and only then `--live`.

## Deploying

### Vercel Cron — for catching cancellations

Good fit for the steady-state case: cancellations trickle out at random
times, and being a few minutes late rarely costs you the table.

```bash
vercel link          # set Root Directory to resy-sniper/
vercel env add RESY_API_KEY RESY_AUTH_TOKEN RESY_VENUE_ID \
               ALERT_EMAIL_FROM ALERT_EMAIL_PASSWORD ALERT_EMAIL_TO \
               RESY_LIVE_BOOKING CRON_SECRET
vercel deploy --prod
```

`CRON_SECRET` is required, not optional: `/api/poll` is a public URL that
books a table, and the handler refuses any request without a matching
`Authorization: Bearer` header. Vercel sends it automatically on cron
invocations.

**Plan limits matter here.** `vercel.json` requests `*/5 * * * *`. On the
Hobby plan, cron jobs are limited to **once per day** and won't run at that
frequency — you need Pro for minute-level schedules. On Hobby this is
effectively a daily availability check, not a sniper.

### Fly.io — for drop-time sniping

If Pizza 4P's releases tables on a schedule (many Resy venues open a
rolling window at a fixed hour), a 5-minute cron will lose to anyone
running a tighter loop. The Fly worker polls continuously instead.

```bash
fly launch --no-deploy --dockerfile deploy/Dockerfile --config deploy/fly.toml
fly secrets set RESY_API_KEY=... RESY_AUTH_TOKEN=... RESY_VENUE_ID=... \
                ALERT_EMAIL_FROM=... ALERT_EMAIL_PASSWORD=... RESY_LIVE_BOOKING=1
fly deploy --config deploy/fly.toml --dockerfile deploy/Dockerfile
```

Note that "sub-second sniping" is bounded by `RESY_MIN_REQUEST_INTERVAL`
and by Resy's own rate limiting — polling harder gets you 429s, not tables.
A ~20s loop that's already running when the window opens beats a burst.

### GitHub Actions — the zero-new-infrastructure option

This repo already runs scheduled jobs this way (`concert-ticket-alerts`).
A `schedule:` workflow calling `python cli.py run --live` with repo secrets
would work too, though Actions cron is best-effort and often runs several
minutes late — fine for cancellations, no good for a drop.

## Layout

| File | Purpose |
| --- | --- |
| `resy_api.py` | HTTP client: find → details → book, with throttling and typed errors |
| `sniper.py` | Date scanning, slot ranking, booking guards — all the logic, no I/O |
| `config.py` | Targets and guardrails, all env-overridable |
| `notify.py` | Confirmation email |
| `runner.py` | One pass over every target; shared by all entry points |
| `cli.py` | `find-venue` / `check` / `run` / `watch` |
| `api/poll.py` | Vercel Cron handler |
| `deploy/` | Fly.io Dockerfile + fly.toml |

## Known gaps

- **Nothing here has been run against the live Resy API.** It was written
  from reverse-engineered docs ([karthikvetrivel/resy-sniper](https://github.com/karthikvetrivel/resy-sniper),
  [jeffknaide/resy-bot](https://github.com/jeffknaide/resy-bot)) and the
  50 unit tests exercise the logic against canned payloads, not real
  responses. Run `check`, then a dry `run`, before trusting `--live`.
- **The `/3/user/reservations` response shape is unverified**, so the
  double-booking guard parses it tolerantly. If it can't reach Resy it logs
  a warning and proceeds rather than blocking a snipe — worth confirming
  against a real response before running unattended for long.
- Slot ranking picks the time closest to the middle of your preferred
  window (~7:30pm for a 6–9pm window), not the earliest. Adjust
  `RESY_PREFERRED_START`/`END` if you'd rather bias early or late.
- Only one target is configured. `config.TARGETS` is a list; add more
  `Target(...)` entries for other restaurants.
