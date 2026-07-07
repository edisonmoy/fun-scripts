# Concert ticket price alerts

Watches resale ticket prices for one or more shows and emails you when
they drop significantly. Also tracks supply (listing counts) and price
across each show's whole tour as a buy-timing signal.

Currently watching: **Noah Kahan - The Great Divide Tour, July 19, 2026 @
Citi Field** (see `config.py`). The project itself isn't specific to that
show - see "Adding another show" below.

## How it works

- **SeatGeek**: uses SeatGeek's free public API (`api.seatgeek.com`) for
  `lowest_price` / `median_price` / `listing_count`. This is the reliable
  core of the system - no scraping, no bot-detection risk.
- **StubHub / Vivid Seats**: no free public API exists, so these are
  scraped with a headless browser (Playwright). Both sites run bot
  detection (confirmed: they 403 plain HTTP requests). The scraper
  (`scrapers/common.py`) works in tiers:
  1. Launch with a stealth pass (patched `navigator.webdriver`, realistic
     UA/viewport/locale/timezone) and jittered pacing/retries.
  2. Listen on the network layer and capture the site's own internal JSON
     responses (listings/GraphQL calls), then scan them for listing-shaped
     data (a price + quantity together) so we get a real "2 tickets
     together" price instead of a guess. This is schema-agnostic since the
     real API shape wasn't observable while building it - see "Known
     limitations".
  3. If no usable JSON was captured, fall back to the cheapest plausible
     `$` amount in the rendered page text (marked `confidence: low`).
  4. If the response looks like a bot-detection challenge (403/429/503, or
     page text matching known challenge-page phrases), the run is marked
     `blocked` instead of guessing at bad data.
- **Self-healing loop**: `health.py` tracks consecutive blocked/error runs
  per source. After `ESCALATION_THRESHOLD` in a row (default 3, ~45 min),
  `github_issue.py` opens a GitHub issue labeled `scraper-blocked` with a
  diagnostic snippet from the failure. A scheduled Claude session
  periodically checks for that label and patches the scraper. The issue
  auto-closes once a source reports healthy data again.
- **Supply/demand signal**: every run also pulls every date on the tour
  from SeatGeek and compares this show's price/listing trend against the
  rest of the tour (see `supply_demand.py`).
- Runs on a GitHub Actions cron every 15 minutes
  (`.github/workflows/concert-ticket-price-check.yml`), committing price
  history back to `data/*.jsonl` and `data/scraper_health.json` so trends
  and failure streaks persist across runs.
- Emails fire when either: the price hits an event's flat dollar target,
  or it drops that event's percent-drop-from-floor threshold below the
  lowest price seen so far for that source.

## Multi-event design

Everything in this project operates on a `WatchedEvent` (`config.py`), not
a hardcoded show. `config.WATCHED_EVENTS` is a list - `main.py` loops over
it and runs the full SeatGeek + StubHub + Vivid Seats + supply/demand
pipeline for each one independently. All storage/health-tracking keys are
namespaced by `event.key`, so events never collide.

### Adding another show

Add a new `WatchedEvent(...)` entry to `config.WATCHED_EVENTS`:

```python
WatchedEvent(
    key="some-artist-some-venue-2026-09-01",  # unique, filesystem-safe
    name="Some Artist - Some Tour",
    date="2026-09-01",
    venue="Some Venue, Some City",
    seatgeek_event_id=12345678,          # from the SeatGeek event URL
    seatgeek_performer_slug="some-artist",  # from seatgeek.com/some-artist-tickets
    stubhub_url="https://www.stubhub.com/...",
    vividseats_url="https://www.vividseats.com/...",
    price_target_per_ticket=200,
    # pct_drop_threshold=15,  # optional, defaults to DEFAULT_PCT_DROP_THRESHOLD
)
```

That's it - no other code changes needed. Each event gets its own price
history, health tracking, and alert emails.

## Setup

1. **SeatGeek API key** (free): sign up at https://seatgeek.com/build and
   grab your client ID.
2. **Email sending**: use a Gmail account with a 2FA
   [App Password](https://myaccount.google.com/apppasswords) (a regular
   password won't work with SMTP).
3. Add these as repo secrets (Settings -> Secrets and variables -> Actions):
   - `SEATGEEK_CLIENT_ID`
   - `ALERT_EMAIL_FROM` - the Gmail address sending the alert
   - `ALERT_EMAIL_PASSWORD` - the App Password (not your normal password)
   - `ALERT_EMAIL_TO` - where to send alerts (can be the same address)
4. Confirm the workflow is enabled under the repo's Actions tab. It runs
   every 15 minutes automatically; you can also trigger it manually via
   "Run workflow" to test it immediately.

## Tuning

Per-event, in `config.WATCHED_EVENTS`:
- `price_target_per_ticket` - flat dollar alert threshold
- `pct_drop_threshold` - percent-drop-from-floor alert threshold (optional,
  falls back to `DEFAULT_PCT_DROP_THRESHOLD`)

Global, in `config.py`:
- `DEFAULT_PCT_DROP_THRESHOLD`
- `MIN_SANE_TICKET_PRICE` / `MAX_SANE_TICKET_PRICE` - sanity bounds used to
  filter junk numbers out of scraped page text
- `ESCALATION_THRESHOLD` - consecutive blocked/error runs before a source
  triggers a GitHub issue

## Linting and tests

`pip install -r requirements-dev.txt`, then from this directory:
- `ruff check .` - lint
- `pytest -q` - unit tests (`tests/`), covering alert thresholds, storage,
  the health/escalation state machine, price/listing extraction and
  bot-block detection, the SeatGeek client, and GitHub issue escalation.
  All mocked/local - no network calls, no real browser.

Both run automatically in CI on any push/PR touching this folder
(`.github/workflows/concert-ticket-checks.yml`).

## Known limitations

- StubHub/Vivid Seats scraping may get blocked entirely if their bot
  detection flags GitHub Actions' IP ranges. If that happens consistently,
  the practical fallback is to treat SeatGeek's price as the primary
  signal - resale prices for the same show tend to move together across
  platforms.
- `scrapers/stubhub.py` / `vividseats.py`'s `API_URL_PATTERN` (which
  network responses to inspect for listing JSON) is a broad guess, not
  observed against the real site - this sandbox's network policy blocks
  these hosts, so it couldn't be verified live. If the "ok" (high
  confidence) status never shows up in the logs, tighten the pattern once
  a real captured request URL/payload is visible (e.g. from an escalated
  issue's diagnostic snippet).
- The text-heuristic fallback's "lowest price" still isn't guaranteed to
  be for 2 adjacent seats specifically, just the cheapest ticket-looking
  price on the page.
