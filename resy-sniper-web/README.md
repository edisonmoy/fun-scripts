# Resy sniper web

Small password-gated dashboard for managing `resy-sniper/targets.json` -
the list of reservations the [resy-sniper](../resy-sniper) bot is
watching. Deployed at resy.edisonmoy.com.

## How it works

There's no database - this reads and writes `resy-sniper/targets.json`
directly via the GitHub Contents API. Saving a change commits to
`master`, which triggers `.github/workflows/resy-sniper-deploy.yml` to
redeploy the bot on Fly.io (targets.json is baked into its Docker image,
not fetched at runtime) - so changes take about 1-2 minutes to go live
after saving. Booking status is read straight off `targets.json` too -
the bot itself (`github_sync.py`) commits a `booking` field once a target
books, so this dashboard is always looking at the same source of truth
the bot uses, not a separate copy.

- `lib/github.ts` - fetch/commit `targets.json` via the GitHub API.
- `lib/claude.ts` - the TypeScript port of `resy-sniper/request_parser.py`,
  used by "Check venue & request" to preview how a target's free-text
  `request` will actually get parsed before you save it.
- `lib/resy.ts` - venue search (same validation flow), live reservation
  lookup, and cancellation. Talks to `api.resy.com` directly with the same
  credentials the bot uses - see [resy-sniper's README](../resy-sniper)
  for what this API is and the risk of using it.
- `lib/auth.ts` + `proxy.ts` - single shared-password gate. The session
  cookie is an HMAC keyed by `AUTH_SECRET`, not the password itself.
- `app/page.tsx` - the dashboard. Watching targets are fully editable
  (each card has its own "Save", which - like every save here - commits
  the whole current file, not just that one card); Booked targets are
  read-only except for a "Cancel reservation" button that shows live
  cancellation terms fetched fresh from Resy (fees/cutoffs are
  time-sensitive, never cached) before you confirm.
- `app/login/page.tsx` - password prompt.

## Validating a target before you trust it

"Check venue & request" (per Watching card) calls Claude and Resy the
same way the bot will, before you save:

- Resolves `venue_name` to an actual Resy venue id + neighborhood/city, so
  you can catch it resolving to the wrong location (chains, similarly-named
  places) before the bot ever polls the wrong venue.
- Parses `request` into the same structured criteria
  (`party_size`/`days_of_week`/time window/`lookahead_weeks`) the bot's
  `request_parser.py` produces, plus a `notes` field flagging anything it
  couldn't represent structurally.

A successful venue resolution fills in the target's `venue_id`
automatically. Neither call blocks Save - it's there so you can catch a
misparse (wrong party size especially) before the bot starts watching on
bad criteria, not a hard gate.

## Local development

```bash
cd resy-sniper-web
npm install
cp .env.example .env.local   # fill in every var below
npm run dev
```

## Environment variables

| Var | What |
| --- | --- |
| `ADMIN_PASSWORD` | Shared password to log in |
| `AUTH_SECRET` | Random string that signs the session cookie |
| `GITHUB_TOKEN` | Fine-grained PAT, scoped to `edisonmoy/fun-scripts`, Contents: read/write |
| `ANTHROPIC_API_KEY` | For "Check venue & request"'s parse preview |
| `RESY_AUTH_TOKEN` / `RESY_API_KEY` | Same values as the bot's Fly secrets - for venue search, live reservation status, and cancellation |

## Known limitations

- Single shared password, no per-user accounts - fine for a personal tool,
  not meant to scale beyond that.
- Optimistic-concurrency only: if you have two browser tabs open and save
  from both, the second save fails with a stale-sha error from GitHub
  rather than silently overwriting - reload and reapply in that case.
- Cancelling always re-looks-up the reservation's current `resy_token`
  from Resy right before cancelling rather than trusting anything stored -
  confirmed live that the token rotates, so a stored one would be stale.
