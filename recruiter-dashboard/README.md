# recruiter-dashboard

A small Next.js dashboard for reviewing recruiter/job-outreach emails that
have been triaged by the `gmail-recruiter-triage` job (in this same repo,
one directory up). That job runs daily via GitHub Actions, reads Edison's
Gmail, classifies each recruiter email, drafts a reply, and writes one row
per email into a shared Postgres `triage_records` table. This dashboard is
the review surface: it lists those rows so drafts can be approved or
rejected, and lets Edison edit his triage preferences (target areas,
seniority, comp floor, autonomy settings, tone notes).

The two projects only communicate through the Postgres database - see
`schema.sql` in each directory for the (identical) shared schema. This
dashboard never talks to Gmail directly and never reads files from
`../gmail-recruiter-triage`; it only reads/writes the shared DB.

Approving a `drafted` row sets its status to `approved_pending`; the next
run of the daily job is what actually sends the reply via Gmail and marks
it `sent`. Rejecting sets it to `rejected`. This dashboard does not send
email itself.

## Schema

`schema.sql` in this directory is a byte-for-byte copy of
`../gmail-recruiter-triage/schema.sql`. It's duplicated (not read
cross-directory at runtime) because Vercel deploys this project with a
scoped root directory, so the sibling file may not be present on disk after
deploy. **If the schema changes, update both copies in the same change.**
The app applies this file's `CREATE TABLE IF NOT EXISTS` / seed statements
once per cold start (see `lib/db.js`), so the dashboard works even if it's
the first thing to ever touch a fresh database.

## Environment variables

- `DATABASE_URL` (required) - a Postgres connection string, e.g.
  `postgres://user:pass@host:5432/dbname`. Works with a local Postgres, or a
  free dev branch on Neon / Vercel Postgres.
- `DASHBOARD_PASSWORD` (required) - the login password for this dashboard.
- `DASHBOARD_AUTH_SECRET` (required) - a random signing secret for the auth
  cookie (not the password itself - see `lib/auth.js`). Generate with e.g.
  `node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"`.

## Running locally

```
npm install
npm run dev
```

You'll need a Postgres instance reachable via `DATABASE_URL` (set it in
`.env.local`, which is gitignored). The app creates its own tables on first
request if they don't already exist.

## Deployment

Deployed as a Vercel project (Next.js App Router, no special build config
needed beyond setting `DATABASE_URL` in the project's environment
variables).

**Important: this dashboard displays sensitive personal data** - recruiter
names/emails, company names, and compensation figures pulled out of
Edison's inbox. Vercel Deployment Protection (password/SSO at the platform
level) requires a Pro plan, which isn't part of this project's plan, so
access control is built into the app itself instead:

- `middleware.js` gates every route except `/login` and `/api/login` behind
  an httpOnly auth cookie, checked *before* any page fetches data from
  Postgres - this matters because the pages are server-rendered with fresh
  DB data on every request (`export const dynamic = 'force-dynamic'`), so a
  client-only (e.g. localStorage) check would not actually prevent an
  unauthenticated request from receiving the rendered HTML.
- `/login` posts a password to `/api/login` (`app/api/login/route.js`),
  which compares it against `DASHBOARD_PASSWORD` and, on success, sets the
  auth cookie to a fixed HMAC digest keyed by `DASHBOARD_AUTH_SECRET` (see
  `lib/auth.js`) - the cookie never encodes the password itself.
- This is intentionally simple (no user table, no session store, single
  shared password) - appropriate for a single-user personal tool, not
  meant to generalize to multiple users.

## Known gaps / follow-ups

- No automated test suite yet. For a personal single-user tool this was
  judged low priority for v1, but API route validation (status/enum
  whitelisting) and the schema-apply-on-boot logic would be reasonable
  first tests to add.
- The full draft text is stored in `triage_records.draft_subject`/
  `draft_body` and rendered inline. If you want to tweak the wording before
  approving, edit the corresponding Gmail draft directly (`gmail_draft_id`)
  - this dashboard doesn't have an edit-in-place UI for the draft text
    itself, only approve/reject.
