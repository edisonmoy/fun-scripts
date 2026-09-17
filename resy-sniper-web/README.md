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
- `lib/claude.ts` - the TypeScript port of `resy-sniper/request_parser.py`
  (including `candidate_dates`/`in_time_window`), used by "Check & Save"
  to preview how a target's free-text `request` will actually get parsed,
  and to know which upcoming dates to probe for a cancellation-terms
  preview.
- `lib/resy.ts` - venue search + detail (for a real address, not just an
  id), live slot search, per-slot detail lookup (cancellation terms),
  live reservation lookup, and cancellation. Talks to `api.resy.com`
  directly with the same credentials the bot uses - see
  [resy-sniper's README](../resy-sniper) for what this API is and the
  risk of using it.
- `lib/auth.ts` + `proxy.ts` - single shared-password gate. The session
  cookie is an HMAC keyed by `AUTH_SECRET`, not the password itself.
- `app/page.tsx` - the dashboard. Each target starts collapsed
  (read-only) once saved; "Edit" opens it back up. Booked targets show
  live cancellation terms and a "Cancel reservation" button.
- `app/login/page.tsx` - password prompt.

## Adding or editing a target

There's no key to type - `+ Add target` generates one, and it's upgraded
to a readable slug (venue + day) the first time "Check & Save" resolves a
real venue. Existing targets keep whatever key they already have.

**"Check & Save" is the only way to save a Watching target** - it's a
single combined action, not two separate steps, and it won't save if
either half fails:

1. Resolves `venue_name` to an actual Resy venue (name + street address,
   not just an id) via the same search the bot uses - so you catch it
   matching the wrong location (chains, similarly-named places) before
   the bot ever polls the wrong venue. Fills in `venue_id` automatically.
2. Parses `request` into the same structured criteria the bot's
   `request_parser.py` produces (`party_size`/`days_of_week`/time
   window/`lookahead_weeks`), plus a `notes` field flagging anything it
   couldn't represent structurally - read this before trusting the parse,
   especially for party size.
3. If a slot matching the parsed criteria happens to be open right now,
   previews that slot's actual cancellation terms (fee, cutoff). Resy only
   sets these per-slot, not per-venue, so a fully-booked venue shows "no
   slot open to preview terms from" instead - that's expected, not an
   error, and isn't required for booking to work once a slot does open.

Only once both venue and request check out does it commit - like every
save here, that's the whole file, not just this one target, so any other
unsaved edits on the page go out too. "Cancel" (next to a target you're
editing) discards your in-progress changes to just that one target and
reverts it to its last-saved state, without touching anything else.

**Notify mode vs. Book mode** - the dashboard's name for what the bot
calls `dry_run`. Notify mode emails you when a matching slot opens but
never books it (and then stops watching that target until the next
restart, so it doesn't re-email you every poll round for the same slot);
Book mode books automatically. New targets default to Notify mode until
you've checked them.

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
| `ANTHROPIC_API_KEY` | For "Check & Save"'s parse preview |
| `RESY_AUTH_TOKEN` / `RESY_API_KEY` | Same values as the bot's Fly secrets - for venue search/detail, live slot search, reservation status, and cancellation |

## Known limitations

- Single shared password, no per-user accounts - fine for a personal tool,
  not meant to scale beyond that.
- Optimistic-concurrency only: if you have two browser tabs open and save
  from both, the second save fails with a stale-sha error from GitHub
  rather than silently overwriting - reload and reapply in that case.
- Cancelling always re-looks-up the reservation's current `resy_token`
  from Resy right before cancelling rather than trusting anything stored -
  confirmed live that the token rotates, so a stored one would be stale.
- The cancellation-terms preview during "Check & Save" probes up to 12
  upcoming candidate dates live against Resy - for a target with narrow
  day-of-week + fully-booked availability, it may find nothing to preview
  even though the bot itself, polling continuously, eventually will.
