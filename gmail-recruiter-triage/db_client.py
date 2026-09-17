import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Module-level connection cache. This runs as a short-lived GitHub Actions
# job (one process, one run) so a single shared connection is simplest -
# there's no server/thread-pool lifecycle to manage.
_connection = None
_schema_applied = False


def _connect():
    global _connection
    if _connection is None or _connection.closed:
        _connection = psycopg.connect(
            os.environ["DATABASE_URL"], row_factory=dict_row, autocommit=True
        )
    return _connection


def _apply_schema(conn):
    """Apply schema.sql, which is written entirely as CREATE TABLE IF NOT
    EXISTS / ON CONFLICT DO NOTHING, so it's safe to run on every process
    start regardless of whether the dashboard (a separate Node app sharing
    this same Postgres database) has already applied it.
    """
    global _schema_applied
    if _schema_applied:
        return
    with conn.cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text())
    _schema_applied = True


def get_connection():
    """Return a live connection, applying schema.sql idempotently the first
    time it's called in this process.
    """
    conn = _connect()
    _apply_schema(conn)
    return conn


def get_preferences():
    """Return the single preferences row as a dict."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM preferences WHERE id = 1")
        return cur.fetchone()


def is_thread_processed(thread_id):
    """True if `thread_id` already has a triage_records row (any status)."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM triage_records WHERE gmail_thread_id = %s", (thread_id,))
        return cur.fetchone() is not None


def upsert_triage_record(
    thread_id,
    received_at,
    sender,
    subject,
    category,
    extracted,
    rationale,
    gmail_draft_id,
    status,
    draft_subject=None,
    draft_body=None,
    fit_score=None,
):
    """Insert or update the triage_records row for `thread_id`. Returns the
    row's id. `draft_subject`/`draft_body` are the actual reply text (if a
    draft was generated) so the dashboard can display it without needing
    Gmail API access itself. `fit_score` (0-100, from the classifier) drives
    the dashboard's fit meter.
    """
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO triage_records (
                gmail_thread_id, received_at, sender, subject, category,
                fit_score, extracted_json, rationale, gmail_draft_id, status,
                draft_subject, draft_body, sent_at
            )
            VALUES (
                %(thread_id)s, %(received_at)s, %(sender)s, %(subject)s, %(category)s,
                %(fit_score)s, %(extracted)s, %(rationale)s, %(gmail_draft_id)s, %(status)s,
                %(draft_subject)s, %(draft_body)s,
                CASE WHEN %(status)s = 'sent' THEN now() ELSE NULL END
            )
            ON CONFLICT (gmail_thread_id) DO UPDATE SET
                received_at = EXCLUDED.received_at,
                sender = EXCLUDED.sender,
                subject = EXCLUDED.subject,
                category = EXCLUDED.category,
                fit_score = EXCLUDED.fit_score,
                extracted_json = EXCLUDED.extracted_json,
                rationale = EXCLUDED.rationale,
                gmail_draft_id = EXCLUDED.gmail_draft_id,
                status = EXCLUDED.status,
                draft_subject = EXCLUDED.draft_subject,
                draft_body = EXCLUDED.draft_body,
                sent_at = CASE
                    WHEN EXCLUDED.status = 'sent' AND triage_records.sent_at IS NULL THEN now()
                    ELSE triage_records.sent_at
                END,
                updated_at = now()
            RETURNING id
            """,
            {
                "thread_id": thread_id,
                "received_at": received_at,
                "sender": sender,
                "subject": subject,
                "category": category,
                "fit_score": fit_score,
                "extracted": Jsonb(extracted),
                "rationale": rationale,
                "gmail_draft_id": gmail_draft_id,
                "status": status,
                "draft_subject": draft_subject,
                "draft_body": draft_body,
            },
        )
        return cur.fetchone()["id"]


def get_needs_analysis_backfill():
    """Rows classified before fit_score existed, or before the company
    description (extracted_json.summary) was a required field - both are
    signs the row predates the current classifier and should be re-run.
    Used to backfill the dashboard's fit meter and company blurb without
    waiting for those threads to naturally reappear as new candidates.
    """
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM triage_records WHERE category != 'ignore' AND "
            "(fit_score IS NULL OR NULLIF(extracted_json->>'summary', '') IS NULL)"
        )
        return cur.fetchall()


def update_analysis(record_id, fit_score, rationale, extracted):
    """Backfill fit_score/rationale/extracted_json for an already-triaged
    row, without touching its status, draft, or Gmail label - this is a
    re-analysis, not a re-triage (category/draft/send decisions stand).
    """
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE triage_records SET fit_score = %s, rationale = %s, "
            "extracted_json = %s, updated_at = now() WHERE id = %s",
            (fit_score, rationale, Jsonb(extracted), record_id),
        )


def get_approved_pending():
    """Rows the dashboard marked to send; the next run should send each
    one's stored draft_subject/draft_body text.
    """
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM triage_records WHERE status = 'approved_pending'")
        return cur.fetchall()


def get_drafted_records():
    """Rows still awaiting review (not yet approved/sent/rejected) - used to
    backfill draft text against a template that didn't exist yet, or was
    edited, when the row was first drafted.
    """
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM triage_records WHERE status = 'drafted'")
        return cur.fetchall()


def update_draft_text(record_id, draft_subject, draft_body):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE triage_records SET draft_subject = %s, draft_body = %s, updated_at = now() "
            "WHERE id = %s",
            (draft_subject, draft_body, record_id),
        )


def mark_sent(record_id):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE triage_records SET status = 'sent', sent_at = now(), updated_at = now() "
            "WHERE id = %s",
            (record_id,),
        )


def get_last_run_at():
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT last_run_at FROM run_state WHERE id = 1")
        row = cur.fetchone()
        return row["last_run_at"] if row else None


def set_last_run_at(dt):
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE run_state SET last_run_at = %s WHERE id = 1", (dt,))
