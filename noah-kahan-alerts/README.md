# Noah Kahan price alerts

Watches ticket prices for the July 19, 2026 Noah Kahan show at Citi Field
and emails you when they drop significantly. Also tracks supply (listing
counts) and price across the whole tour as a buy-timing signal.

## How it works

- **SeatGeek**: uses SeatGeek's free public API (`api.seatgeek.com`) for
  `lowest_price` / `median_price` / `listing_count`. This is the reliable
  core of the system - no scraping, no bot-detection risk.
- **StubHub / Vivid Seats**: no free public API exists, so these are
  scraped with a headless browser (Playwright). Both sites run bot
  detection (confirmed: they 403 plain HTTP requests), so these scrapers
  are best-effort. They extract the cheapest plausible `$` amount from the
  rendered page rather than a guaranteed "2 seats together" price. Expect
  to need to fix selectors/approach after watching a few real runs - check
  the Action logs (`[stubhub] FAILED` / `[vividseats] FAILED`) if a source
  stops reporting.
- **Supply/demand signal**: every run also pulls every date on the tour
  from SeatGeek and compares this show's price/listing trend against the
  rest of the tour (see `supply_demand.py`).
- Runs on a GitHub Actions cron every 15 minutes (`.github/workflows/noah-kahan-price-check.yml`),
  committing price history back to `data/*.jsonl` so trends persist across runs.
- Emails fire when either: the price hits your flat dollar target, or it
  drops `PCT_DROP_THRESHOLD`% below the lowest price seen so far for that
  source. Both are configurable in `config.py`.

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

Edit `config.py`:
- `PRICE_TARGET_PER_TICKET` - flat dollar alert threshold
- `PCT_DROP_THRESHOLD` - percent-drop-from-floor alert threshold
- `MIN_SANE_TICKET_PRICE` / `MAX_SANE_TICKET_PRICE` - sanity bounds used to
  filter junk numbers out of scraped page text

## Linting

`pip install -r requirements-dev.txt` then `ruff check .` from this
directory. Runs automatically in CI on any push/PR touching this folder
(`.github/workflows/noah-kahan-lint.yml`).

## Known limitations

- StubHub/Vivid Seats scraping may get blocked entirely if their bot
  detection flags GitHub Actions' IP ranges. If that happens consistently,
  the practical fallback is to treat SeatGeek's price as the primary
  signal - resale prices for the same show tend to move together across
  platforms.
- The scraped "lowest price" is not guaranteed to be for 2 adjacent seats
  specifically, just the cheapest ticket listed on the page.
