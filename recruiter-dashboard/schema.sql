-- Applied idempotently once per cold start (see lib/db.js): everything is
-- CREATE ... IF NOT EXISTS, ON CONFLICT DO NOTHING, or an idempotent
-- migration, so it's safe to run against a fresh or an existing database.

CREATE TABLE IF NOT EXISTS preferences (
    id INTEGER PRIMARY KEY DEFAULT 1,
    target_areas TEXT NOT NULL DEFAULT '',
    seniority TEXT NOT NULL DEFAULT '',
    comp_floor INTEGER,
    company_excludes TEXT NOT NULL DEFAULT '',
    -- Optional custom reply templates for keep_warm/high_interest, used
    -- verbatim (placeholders filled in). Empty means the model drafts a
    -- reply from lib/triage/draftWriter.js's built-in style instead.
    keep_warm_template TEXT NOT NULL DEFAULT '',
    high_interest_template TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT preferences_single_row CHECK (id = 1)
);

CREATE TABLE IF NOT EXISTS triage_records (
    id SERIAL PRIMARY KEY,
    gmail_thread_id TEXT NOT NULL UNIQUE,
    received_at TIMESTAMPTZ,
    sender TEXT,
    subject TEXT,
    category TEXT NOT NULL CHECK (category IN ('ignore', 'keep_warm', 'high_interest')),
    fit_score INTEGER,
    extracted_json JSONB NOT NULL DEFAULT '{}',
    rationale TEXT,
    gmail_draft_id TEXT,
    -- The reply text drafted for this thread, reviewed and sent from the
    -- dashboard. Null for category='ignore' rows.
    draft_subject TEXT,
    draft_body TEXT,
    -- When the reply actually went out. Null until status='sent'. Distinct from
    -- received_at (the original email) and created_at (when this row was
    -- first triaged) so the dashboard can show both dates on sent items.
    sent_at TIMESTAMPTZ,
    -- drafted: draft created, awaiting review in the dashboard
    -- approved_pending: legacy (queued for the old GitHub Actions job to send);
    --   no longer written - migrated back to drafted below
    -- sent: the reply went out (sent from the dashboard)
    -- ignored: classifier decided this wasn't worth a reply (kept for dedupe/audit)
    -- rejected: user explicitly rejected a drafted reply from the dashboard
    status TEXT NOT NULL DEFAULT 'drafted'
        CHECK (status IN ('drafted', 'approved_pending', 'sent', 'ignored', 'rejected')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS run_state (
    id INTEGER PRIMARY KEY DEFAULT 1,
    last_run_at TIMESTAMPTZ,
    -- Lease held while a dashboard sync runs, so two can't overlap. Expires
    -- on its own if a sync dies mid-flight (see lib/triage/records.js).
    sync_locked_until TIMESTAMPTZ,
    CONSTRAINT run_state_single_row CHECK (id = 1)
);

INSERT INTO preferences (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
INSERT INTO run_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- Migrations for databases created before these columns existed - CREATE
-- TABLE IF NOT EXISTS above is a no-op against an already-live table, so
-- this covers upgrading it in place. Safe to run every time.
ALTER TABLE triage_records ADD COLUMN IF NOT EXISTS fit_score INTEGER;
ALTER TABLE preferences ADD COLUMN IF NOT EXISTS keep_warm_template TEXT NOT NULL DEFAULT '';
ALTER TABLE preferences ADD COLUMN IF NOT EXISTS high_interest_template TEXT NOT NULL DEFAULT '';
ALTER TABLE preferences DROP COLUMN IF EXISTS tone_notes;
-- Auto-send was removed: every reply is reviewed and sent from the dashboard.
ALTER TABLE preferences DROP COLUMN IF EXISTS autonomy_keep_warm;
ALTER TABLE preferences DROP COLUMN IF EXISTS autonomy_high_interest;
ALTER TABLE preferences DROP COLUMN IF EXISTS keep_warm_auto_send_max_fit;
ALTER TABLE preferences DROP COLUMN IF EXISTS high_interest_auto_send_min_fit;
-- Triage moved from GitHub Actions into the dashboard's own sync.
ALTER TABLE run_state DROP COLUMN IF EXISTS active_run_id;
ALTER TABLE run_state ADD COLUMN IF NOT EXISTS sync_locked_until TIMESTAMPTZ;
-- Rows queued for the old job to send go back to review instead of being
-- sent without a fresh click.
UPDATE triage_records SET status = 'drafted', updated_at = now() WHERE status = 'approved_pending';
ALTER TABLE triage_records ADD COLUMN IF NOT EXISTS sent_at TIMESTAMPTZ;
-- Best-effort backfill for rows sent before sent_at existed: updated_at is
-- the closest proxy we have (it's set on every write, and a 'sent' row's
-- last write was the send itself).
UPDATE triage_records SET sent_at = updated_at WHERE status = 'sent' AND sent_at IS NULL;
