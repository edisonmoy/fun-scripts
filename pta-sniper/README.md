# PTA sniper

Watches one specific screening - Paul Thomas Anderson's *Cameron Winter at
Carnegie Hall*, world premiere, **Thu Oct 1 2026, 9:15 PM, Alice Tully Hall**
(NYFF64, Tessitura performance id `84536`) - and tries to alert/buy the
instant it's no longer sold out.

**Read "Known limitations" before trusting this to actually buy anything.**
Unlike `resy-sniper` (a documented-enough private API with no real bot
defenses) or `concert-ticket-alerts` (alert-only, never tries to buy), this
site runs real bot mitigation on the purchase flow, confirmed live during
development. The alert half of this bot is solid; the auto-purchase half is
best-effort and may simply not work.

## Current status of the screening (as of 2026-09-24)

The screening is **sold out**. filmlinc.org's own purchase page says:

> If an event is eligible for standby, on the day of the screening, a
> standby line will form at the corresponding venue's box office prior to
> showtime. Tickets may become available to the standby line on a
> first-come, first-served basis one (1) per customer.

That's a physical, day-of, in-person line at Alice Tully Hall's box
office - not an online queue or return/resale mechanism. There's no
confirmed evidence Film at Lincoln Center re-releases returned/exchanged
tickets online in real time (unlike Resy, where a cancellation reliably
reopens a slot via the API within seconds). This bot only catches the case
where the performance's `available` flag flips back to true on the public
event page - if that never happens, going in person for the standby line is
the only route.

## How it works

- `availability.py` - loads the public film page
  (`https://www.filmlinc.org/nyff2026/films/cameron-winter-at-carnegie/`)
  with a headless browser (needed - Cloudflare's JS challenge blocks a
  plain HTTP GET) and greps the performance's showtime data (`available`,
  `status`, date/time) out of the page's embedded JSON. This part is
  low-risk and worked reliably in testing - no bot-blocking observed on
  a plain page load.
- `main.py` - polls that on an interval, and the moment `available` flips
  true: **always sends an alert email immediately** (the reliable part),
  then, unless `PTA_DRY_RUN` is set, attempts an automated purchase via
  `checkout.py`. If the automated purchase fails, a second email says so
  and repeats the buy link - the first alert already gave you a shot at
  buying it by hand regardless of whether automation works.
- `checkout.py` - best-effort Playwright automation: log in to your
  filmlinc.org (Tessitura) account, load the purchase page, select
  quantity, add to cart, check out with your account's saved payment
  method. **See "Known limitations" - most of this flow is unverified.**
- `alerts.py` - Gmail SMTP, same as `resy-sniper`/`concert-ticket-alerts`.

## Known limitations (read this)

- **Login is confirmed blocked by bot detection in testing.** Submitting
  the real login form via a headless Playwright browser got intercepted by
  the site's **Imperva Incapsula** WAF - the response was an "Incapsula
  incident" challenge page, not the real login result. This happened on
  the very first attempt, not after repeated hammering, which is a strong
  signal this isn't reliably automatable as-is - the same conclusion
  `concert-ticket-alerts`' README reached for StubHub.
  - This test ran from inside a sandboxed dev environment whose outbound
    traffic goes through a TLS-intercepting proxy (a different TLS/JA3
    fingerprint than a real browser talking directly to the internet) -
    that may have contributed to the block. The deployed bot (Fly.io, real
    egress, no intercepted TLS) hasn't been tested live and might fare
    differently. **Verify with a supervised dry run before trusting this**,
    the same way `resy-sniper`'s README insists on watching dry-run logs
    before flipping `RESY_DRY_RUN=false`.
- **The public film page's own Cloudflare JS challenge got measurably
  harder to pass over the course of one testing session.** Early requests
  solved in ~6s; by the end of ~20 minutes of repeated automated page
  loads from the same sandbox, it stopped resolving at all within 20s.
  This looks like exactly the kind of escalating scrutiny `resy-sniper`'s
  README warns about for tight poll loops - worth keeping
  `PTA_POLL_INTERVAL_SECONDS` reasonable (60s default) rather than pushing
  it low, and worth treating a run of `AvailabilityError`s from the
  deployed bot as "back off", which `main.py` already does.
- **The buy widget (ticket type/quantity selector, Add to Cart) never
  rendered in testing**, even on screenings confirmed genuinely available
  (checked several from NYFF's "available tickets" filter). The page also
  carries a Queue-it `queueittoken` with an `rt_safetynet` field on every
  URL, which suggests Queue-it's bot-detection layer may be silently
  withholding the interactive purchase controls from automated clients
  rather than erroring - `checkout.py`'s selectors past login are
  therefore **unverified guesses** based on Tessitura's common `tn-`
  class-naming conventions, not an observed real DOM.
- Given the above, `checkout.py` is written to fail loudly and specifically
  (which step it got stuck on) rather than silently do nothing, and
  `main.py` never depends on it succeeding - the alert always goes out
  first. Update `checkout.py`'s selectors from real observed markup the
  first time a genuine opening lets you watch the flow live (or from a
  screenshot taken at the point it got stuck).
- No account/payment automation has touched your real account beyond the
  one blocked login test - no card was added, nothing was purchased.
- Ticket limit is 2 per household per screening (site-enforced) -
  `PTA_TICKET_QUANTITY` defaults to 2 and is clamped to that in
  `checkout.py`.

## Setup

1. **Add a payment method to your filmlinc.org account yourself**, in your
   own real browser (not through this bot - login automation is the part
   confirmed blocked, and a saved card is needed either way since
   `checkout.py` never handles a raw card number itself, only an
   account's saved one):
   - Log in at https://purchase.filmlinc.org/account/login
   - Look under your account/profile area for a payment methods section
     (exact path unconfirmed here - login automation never got far enough
     to observe it live). If you don't see one, FLC's box office
     (212.875.5601) or the site's chat widget can point you to it, or a
     saved card may only get requested the first time you actually check
     out.
2. **Gmail app password** for alert emails: same as the other projects -
   https://myaccount.google.com/apppasswords.
3. Copy `.env.example` to `.env` and fill in `PTA_FLC_EMAIL`,
   `PTA_FLC_PASSWORD`, `ALERT_EMAIL_FROM`, `ALERT_EMAIL_PASSWORD`,
   `ALERT_EMAIL_TO`.

## Run it locally (dry run first)

```bash
cd pta-sniper
pip install -r requirements-dev.txt
playwright install chromium   # only needed for local dev; the Docker image ships it
pytest                        # unit tests, no network/credentials needed

export $(cat .env | xargs)
python main.py                 # PTA_DRY_RUN=true by default - alerts only, never buys
```

Watch the logs - it checks every ~60s by default (`PTA_POLL_INTERVAL_SECONDS`).
You should see `still sold out: ...` each round. Leave this running; if the
status ever changes, confirm the alert email arrives, then decide whether to
trust `PTA_DRY_RUN=false` based on what `checkout.py` logs when it actually
gets a chance to run against a real opening.

## Deploy to Fly.io (always-on polling)

```bash
fly launch --no-deploy   # picks up fly.toml, creates the app, skip the first auto-deploy
fly secrets set \
  PTA_FLC_EMAIL=... \
  PTA_FLC_PASSWORD=... \
  ALERT_EMAIL_FROM=... \
  ALERT_EMAIL_PASSWORD=... \
  ALERT_EMAIL_TO=moyedison@gmail.com \
  PTA_DRY_RUN=true
fly deploy
fly logs   # confirm it's polling
```

Flip `PTA_DRY_RUN=false` (`fly secrets set PTA_DRY_RUN=false`) only once
you're comfortable with the risk described above - an opening might still
be missed or fail to auto-purchase, but the alert will still fire either
way if the bot is running.

## Config reference

| Var | Default | What |
| --- | --- | --- |
| `PTA_DRY_RUN` | `true` | `false` lets it attempt a real automated purchase; otherwise alert-only |
| `PTA_TICKET_QUANTITY` | `2` | Tickets to request (site max is 2/household) |
| `PTA_POLL_INTERVAL_SECONDS` / `PTA_POLL_JITTER_SECONDS` | `60` / `10` | Poll cadence |
| `PTA_FLC_EMAIL` / `PTA_FLC_PASSWORD` | _(required for auto-purchase)_ | Your filmlinc.org account |
| `PTA_FILM_PAGE_URL` / `PTA_PERFORMANCE_ID` / `PTA_PURCHASE_URL` | _(pre-set for this screening)_ | Override only if watching a different NYFF showtime |
| `ALERT_EMAIL_FROM` / `ALERT_EMAIL_PASSWORD` / `ALERT_EMAIL_TO` | _(required)_ | Gmail SMTP for alert emails |

## Linting and tests

`pip install -r requirements-dev.txt`, then from this directory:
- `ruff check .`
- `pytest -q` - covers availability-JSON parsing against the real captured
  shape (sold out and a synthetic available case). No network calls, no
  real browser, no credentials.
