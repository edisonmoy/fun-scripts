# Gmail recruiter triage

Daily job that triages Edison's recruiter/job-outreach emails in Gmail.
Most recruiter emails get a warm, low-commitment "not right now, keep me
in mind" reply. Emails matching his real interests - healthcare AI focused
on patient outcomes (not administrative/scheduling tooling), climate tech,
and venture-studio-style opportunities - get a more substantive draft plus
a structured summary in a companion dashboard (a separate app, not part of
this repo, that reads/writes the same Postgres database via `schema.sql`).

## How it works

1. Load `preferences` (target areas, seniority, comp floor, company
   excludes, autonomy settings, tone notes) from Postgres.
2. Search Gmail for candidate threads since the last run (`run_state.
   last_run_at`), using a broad keyword heuristic
   (`config.GMAIL_SEARCH_QUERY`) restricted to `in:inbox`. Threads already
   present in `triage_records` (any status) are skipped.
3. For each new candidate thread:
   - Fetch the plaintext of its most recent message.
   - Classify it against `preferences` via a forced tool-use call to the
     Anthropic API (`classifier.py`) - the model must call a strictly
     schema-validated tool, so there's no free-text parsing of the
     classification.
   - If it's not recruiter outreach at all, record `category="ignore"`,
     `status="ignored"` (for dedupe/audit) and move on.
   - Otherwise, apply the category's Gmail label (`Recruiter/KeepWarm`,
     `Recruiter/HighInterest`, or `Recruiter/Ignored`), generate a reply
     draft (`draft_writer.py`) that explicitly references the specific
     company/role from the email (never a generic template - recruiters
     can tell), and run it through the quality gate (`quality_gate.py`).
   - A draft that fails the gate is stored with `status="drafted"` and no
     `gmail_draft_id`, for manual follow-up - it is **never** auto-sent.
   - A draft that passes gets created in Gmail. If the category's autonomy
     setting (`preferences.autonomy_keep_warm` /
     `autonomy_high_interest`) is `auto_send`, it's sent immediately
     (`status="sent"`); otherwise it's left as `status="drafted"` for
     manual review (in Gmail or the dashboard).
4. Send the Gmail draft for every `triage_records` row the dashboard
   marked `approved_pending`, then mark it `sent`.
5. Update `run_state.last_run_at`.
6. Write a `GITHUB_STEP_SUMMARY` table of **aggregate counts only** (see
   below).

Each candidate thread is processed inside its own `try/except` so one bad
thread (a malformed email, a transient API error) doesn't fail the whole
run - it's logged (by thread id and exception type only) and counted as an
error.

### Design decision: no sensitive content in logs or step summaries

`fun-scripts` is a **public** GitHub repository, and Actions logs and step
summaries for a public repo are publicly visible to anyone, logged in or
not. Recruiter emails, sender addresses, subject lines, company/role
names, comp figures, and draft text are all sensitive. To keep this safe
to run in a public repo, this project **never** logs or writes to
`GITHUB_STEP_SUMMARY` any of that content - only aggregate counts (e.g.
"processed 5 candidate threads: 2 keep_warm, 1 high_interest, 2 ignored, 0
errors") and opaque identifiers (Gmail thread ids, DB row ids). This is
strictly more restrictive than `concert-ticket-alerts`' logging in this
repo - that project's data (ticket prices) isn't sensitive, so it logs
prices/venues freely; this one's data is, so it doesn't. If you're
extending this project, keep new log lines to counts/ids/exception types -
never interpolate subject/sender/body/draft text into a log message.

## Setup

1. **Google Cloud OAuth app**: in Google Cloud Console, create a project
   (or reuse one), enable the Gmail API, and create an OAuth client of
   type "Desktop app" under APIs & Services -> Credentials.
2. **Get a refresh token**: run `python authorize.py` locally (see its
   docstring) with that client's id/secret. It opens a browser consent
   flow for the `gmail.modify`, `gmail.compose`, and `gmail.send` scopes
   and prints a refresh token - this is a one-time manual step, not run by
   the GitHub Action.
3. **Anthropic API key**: from the Anthropic Console.
4. **Postgres database**: any Postgres instance reachable from GitHub
   Actions; `db_client.py` applies `schema.sql` idempotently on every run,
   so no manual migration step is needed. The dashboard (built separately)
   applies the same `schema.sql` against the same database.
5. Add these as GitHub repo secrets (Settings -> Secrets and variables ->
   Actions):
   - `GMAIL_CLIENT_ID`
   - `GMAIL_CLIENT_SECRET`
   - `GMAIL_REFRESH_TOKEN` - from step 2
   - `ANTHROPIC_API_KEY`
   - `DATABASE_URL`
6. Confirm the workflow is enabled under the repo's Actions tab. It runs
   once daily automatically; you can also trigger it manually via "Run
   workflow" to test it.

## Tuning

`preferences` and `run_state` are single-row tables (see `schema.sql`),
edited either through the dashboard (recommended) or directly via SQL as a
fallback:

```sql
UPDATE preferences SET
    target_areas = 'healthcare AI (patient outcomes, not admin/scheduling), climate tech, venture studios',
    seniority = 'Staff / Principal',
    comp_floor = 250000,
    company_excludes = 'CurrentEmployerInc',
    autonomy_keep_warm = 'auto_send',
    autonomy_high_interest = 'draft_only',
    tone_notes = 'Warm but brief. No exclamation points.'
WHERE id = 1;
```

Other tunables live in `config.py`:

- `ANTHROPIC_MODEL` - overridable via the `ANTHROPIC_MODEL` env var
- `MIN_DRAFT_LENGTH` / `PLACEHOLDER_MARKERS` - the quality gate's
  thresholds
- `CATEGORY_LABELS` - Gmail label names per category
- `GMAIL_SEARCH_QUERY` - the keyword heuristic used to shortlist candidate
  threads
- `DEFAULT_LOOKBACK_DAYS` - how far back to search on the very first run,
  before `run_state.last_run_at` exists

## Linting and tests

`pip install -r requirements-dev.txt`, then from this directory:

- `ruff check .` - lint
- `pytest -q` - unit tests (`tests/`), covering the classifier's forced
  tool-use response parsing, the quality gate's reject/pass cases, the DB
  client (mocked psycopg connection/cursor), and `main.py`'s
  auto-send-vs-draft-only branching and approved-pending processing. All
  mocked - no live network calls, no real database, no real Gmail/Anthropic
  API calls.

Both run automatically in CI on any push/PR touching this folder
(`.github/workflows/gmail-recruiter-checks.yml`).

## Known limitations

- Gmail's `after:` search operator is date-granularity only (no
  time-of-day), so a run can re-search threads from earlier the same
  calendar day as the previous run. This is harmless -
  `is_thread_processed()` dedupes against `triage_records` before doing
  any real work on a thread.
- The extracted `comp` field is LLM-inferred, best-effort parsing of
  whatever figure (if any) the email happened to mention - it is not
  guaranteed accurate and should be treated as a hint, not a fact.
- This is a single-user personal tool: `preferences` and `run_state` are
  intentionally single-row tables (`id = 1`), not per-user.
- The classifier and draft writer each make one Anthropic API call per
  candidate thread with no retry/backoff beyond the SDK's default - a
  transient API failure on one thread is caught, logged (by thread id
  only), and counted as an error rather than failing the whole run, but
  that thread won't be retried until the underlying Gmail search
  re-surfaces it (e.g. within the `after:` re-search window above).
