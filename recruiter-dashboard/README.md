# recruiter-dashboard

A small Next.js app for triaging Edison's recruiter/job-outreach email. It
pulls candidate threads from Gmail, classifies each one against his
preferences, drafts a reply, and lists everything for review. **Nothing is
ever sent without a click:** every reply waits in the dashboard until
Edison sends it himself.

## How it works

**Sync (the "Sync" button).** There's no schedule or background job; triage
only runs when the button is clicked. Each click calls `POST /api/sync`
repeatedly until it reports nothing left. Each call is one time-boxed batch
(`lib/triage/sync.js`):

1. Search Gmail for candidate threads since the last completed sync
   (`run_state.last_run_at`), using a broad keyword heuristic
   (`GMAIL_SEARCH_QUERY` in `lib/triage/config.js`) restricted to
   `in:inbox`. Threads already in `triage_records` (any status) are skipped.
2. For each new thread, until the batch has run ~20s:
   - Fetch the plaintext of its most recent message.
   - Classify it via the Anthropic API (`lib/triage/classifier.js`). The
     model may `web_search` a named company first, since an email's own
     framing can be generic even when the company is a clear match (or
     non-match). A strict tool schema means no free-text parsing, and a
     forced follow-up call guarantees a classification even if the model
     stops after searching.
   - Not recruiter outreach, or classified `ignore`: stored as
     `status="ignored"` for dedupe/audit, with no draft.
   - Otherwise: apply the category's Gmail label (`Recruiter/KeepWarm`,
     `Recruiter/HighInterest`) and draft a reply (`lib/triage/draftWriter.js`).
     A custom template for the category (`preferences.keep_warm_template` /
     `high_interest_template`) is used **verbatim** with `<name>`,
     `<company>`, `<role>` filled in, with no model call. Without one, the
     model drafts a reply required to reference specifics from the email.
     Stored as `status="drafted"`.
3. `last_run_at` only advances once a sync fully catches up with no failed
   threads, so a failure can't fall outside the next sync's search window.

A thread that fails is skipped for the rest of that sync and retried on the
next one. A lease on `run_state.sync_locked_until` stops two syncs (two tabs,
double clicks) from overlapping. It expires on its own if a sync dies.

**Send.** "Send" calls `POST /api/triage/[id]/send`, which sends immediately
via Gmail (`lib/triage/send.js`). It first claims the row with a conditional
`drafted -> sent` update, so a double click or a second tab can never send
the same reply twice. If Gmail rejects the send, the claim is released and
the row goes back to `drafted`. The reply carries `In-Reply-To`/`References`
headers and the thread's own subject, so it stays threaded in the
recruiter's mail client, not just in Edison's Gmail.

**Templates.** Saving preferences re-applies an edited template to every
still-drafted row right away.

## Schema

`schema.sql` is applied idempotently once per cold start (see `lib/db.js`):
`CREATE TABLE IF NOT EXISTS`, seed rows, and in-place migrations, so the app
works against a fresh database or an existing one.

## Environment variables

- `DATABASE_URL` (required) - Postgres connection string.
- `DASHBOARD_PASSWORD` (required) - the login password.
- `DASHBOARD_AUTH_SECRET` (required) - random secret that signs the auth
  cookie (not the password itself - see `lib/auth.js`). Generate with e.g.
  `node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"`.
- `ANTHROPIC_API_KEY` (required) - for classification and drafting.
- `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` (required)
  - Gmail OAuth credentials. Mint the refresh token with
  `scripts/authorize_gmail.py` (instructions in the script).
- `ANTHROPIC_MODEL` (optional) - overrides the model (default
  `claude-sonnet-5`).

## Running locally

```
npm install
npm run dev
npm test
```

Put the variables above in `.env.local` (gitignored). The app creates its
own tables on first request.

## Deployment

Deployed as a Vercel project with **Root Directory set to
`recruiter-dashboard`** (the repo root has no Next.js app, so a build from
there fails). No other build config is needed beyond the environment
variables above.

**This app displays sensitive personal data** - recruiter names/emails,
company names, and compensation figures from Edison's inbox. Vercel
Deployment Protection requires a Pro plan, so access control is built in:

- `middleware.js` gates every route except `/login` and `/api/login` behind
  an httpOnly auth cookie, checked *before* any page reads Postgres - pages
  are server-rendered with fresh data on every request, so a client-only
  check wouldn't stop an unauthenticated request from getting the HTML.
- `/api/login` compares the password against `DASHBOARD_PASSWORD` and sets
  the cookie to a fixed HMAC digest keyed by `DASHBOARD_AUTH_SECRET` - the
  cookie never encodes the password itself.
- Single shared password, no user table - fine for a single-user tool.

Server logs never include email content (senders, subjects, company names,
comp, draft text), only opaque ids and error messages.

## Known gaps

- There's no edit-in-place for draft text: send it as drafted, or reject
  it and reply from Gmail.
