import { query } from '../db'

// A sync holds this lease while it works, so two tabs (or two clicks) can't
// triage the same new threads at once. It outlives the sync route's
// maxDuration, so a sync killed mid-flight frees the lock on its own.
const SYNC_LEASE_SECONDS = 90

export async function acquireSyncLock() {
  const { rows } = await query(
    `UPDATE run_state SET sync_locked_until = now() + make_interval(secs => $1)
     WHERE id = 1 AND (sync_locked_until IS NULL OR sync_locked_until < now())
     RETURNING id`,
    [SYNC_LEASE_SECONDS]
  )
  return rows.length > 0
}

export async function releaseSyncLock() {
  await query('UPDATE run_state SET sync_locked_until = NULL WHERE id = 1')
}

export async function getLastRunAt() {
  const { rows } = await query('SELECT last_run_at FROM run_state WHERE id = 1')
  return rows[0]?.last_run_at || null
}

export async function setLastRunAt(date) {
  await query('UPDATE run_state SET last_run_at = $1 WHERE id = 1', [date])
}

export async function getPreferences() {
  const { rows } = await query('SELECT * FROM preferences WHERE id = 1')
  return rows[0] || {}
}

// The subset of `threadIds` that already have a triage_records row.
export async function getProcessedThreadIds(threadIds) {
  if (threadIds.length === 0) return new Set()
  const { rows } = await query(
    'SELECT gmail_thread_id FROM triage_records WHERE gmail_thread_id = ANY($1)',
    [threadIds]
  )
  return new Set(rows.map((r) => r.gmail_thread_id))
}

export async function insertTriageRecord(record) {
  // DO NOTHING on conflict: the sync lock already prevents two syncs from
  // processing the same thread, and an existing row must never be
  // overwritten back to 'drafted' (it may have been sent since).
  await query(
    `INSERT INTO triage_records (
       gmail_thread_id, received_at, sender, subject, category, fit_score,
       extracted_json, rationale, status, draft_subject, draft_body
     )
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
     ON CONFLICT (gmail_thread_id) DO NOTHING`,
    [
      record.threadId,
      record.receivedAt,
      record.sender,
      record.subject,
      record.category,
      record.fitScore ?? null,
      JSON.stringify(record.extracted),
      record.rationale ?? null,
      record.status,
      record.draftSubject ?? null,
      record.draftBody ?? null,
    ]
  )
}

// Atomically flips a drafted row to 'sent' *before* sending it, returning
// the row only to the one caller whose UPDATE matched - so a double click or
// a second tab can't send the same reply twice.
export async function claimForSend(id) {
  const { rows } = await query(
    `UPDATE triage_records SET status = 'sent', sent_at = now(), updated_at = now()
     WHERE id = $1 AND status = 'drafted' AND draft_body IS NOT NULL
     RETURNING *`,
    [id]
  )
  return rows[0] || null
}

// Undoes claimForSend after a failed send so the row can be sent again.
export async function releaseSendClaim(id) {
  await query(
    `UPDATE triage_records SET status = 'drafted', sent_at = NULL, updated_at = now()
     WHERE id = $1 AND status = 'sent'`,
    [id]
  )
}

export async function getDraftedRecords() {
  const { rows } = await query("SELECT * FROM triage_records WHERE status = 'drafted'")
  return rows
}

export async function updateDraftText(id, subject, body) {
  await query(
    'UPDATE triage_records SET draft_subject = $1, draft_body = $2, updated_at = now() WHERE id = $3',
    [subject, body, id]
  )
}
