-- Mirrors gmail-recruiter-triage/schema.sql exactly. Duplicated here (rather
-- than read cross-directory at runtime) because Vercel deploys this project
-- with a scoped root directory, so the sibling file isn't guaranteed to be
-- reachable on disk after deploy. If you change the schema, update BOTH
-- copies in the same change.

CREATE TABLE IF NOT EXISTS preferences (
    id INTEGER PRIMARY KEY DEFAULT 1,
    target_areas TEXT NOT NULL DEFAULT '',
    seniority TEXT NOT NULL DEFAULT '',
    comp_floor INTEGER,
    company_excludes TEXT NOT NULL DEFAULT '',
    autonomy_keep_warm TEXT NOT NULL DEFAULT 'draft_only'
        CHECK (autonomy_keep_warm IN ('draft_only', 'auto_send')),
    autonomy_high_interest TEXT NOT NULL DEFAULT 'draft_only'
        CHECK (autonomy_high_interest IN ('draft_only', 'auto_send')),
    -- Extra gate on top of the auto_send toggles above: when set, a
    -- category's autonomy=auto_send only actually auto-sends if fit_score
    -- also clears this bar. Null means no extra gate (all-or-nothing, as
    -- the toggle alone implies). Directionality differs on purpose:
    -- keep_warm auto-sends the LOW-fit ones (clearly generic outreach,
    -- safe to auto-dismiss); high_interest auto-sends the HIGH-fit ones
    -- (confidently a strong match).
    keep_warm_auto_send_max_fit INTEGER,
    high_interest_auto_send_min_fit INTEGER,
    -- Optional custom instructions for keep_warm replies. Empty means fall
    -- back to draft_writer.py's built-in three-part default.
    keep_warm_template TEXT NOT NULL DEFAULT '',
    tone_notes TEXT NOT NULL DEFAULT '',
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
    -- The actual reply text created for this thread (mirrors what was put
    -- in the Gmail draft), stored here so the dashboard can show it without
    -- needing Gmail API access itself. Null for category='ignore' rows.
    draft_subject TEXT,
    draft_body TEXT,
    -- drafted: draft created, awaiting manual send in Gmail or dashboard action
    -- approved_pending: dashboard marked it to send; next Action run sends it
    -- sent: the reply went out (auto_send or approved_pending -> sent)
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
    CONSTRAINT run_state_single_row CHECK (id = 1)
);

INSERT INTO preferences (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
INSERT INTO run_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- Migrations for databases created before these columns existed - CREATE
-- TABLE IF NOT EXISTS above is a no-op against an already-live table, so
-- this covers upgrading it in place. Safe to run every time.
ALTER TABLE triage_records ADD COLUMN IF NOT EXISTS fit_score INTEGER;
ALTER TABLE preferences ADD COLUMN IF NOT EXISTS keep_warm_auto_send_max_fit INTEGER;
ALTER TABLE preferences ADD COLUMN IF NOT EXISTS high_interest_auto_send_min_fit INTEGER;
ALTER TABLE preferences ADD COLUMN IF NOT EXISTS keep_warm_template TEXT NOT NULL DEFAULT '';
