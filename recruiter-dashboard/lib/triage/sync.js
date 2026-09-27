import { classify } from './classifier'
import { CATEGORY_LABELS, DEFAULT_LOOKBACK_DAYS, GMAIL_SEARCH_QUERY } from './config'
import { draftReply } from './draftWriter'
import * as gmail from './gmail'
import * as records from './records'

// PRIVACY: never log email content (senders, subjects, company names, comp,
// draft text) - only opaque ids and error messages.

// Stop starting new threads once a batch has run this long. Classifying one
// thread that escalates to web research can take tens of seconds, so this keeps a batch
// well inside the sync route's maxDuration; the client calls again for the
// rest.
export const BATCH_BUDGET_MS = 20_000

export class SyncBusyError extends Error {}

// Classifies one thread, labels it in Gmail, drafts a reply, and records
// it. Never sends anything - every reply waits for review in the dashboard.
async function triageThread(threadId, preferences) {
  const thread = await gmail.getThreadPlaintext(threadId)
  const classification = await classify(thread, preferences)
  const base = {
    threadId,
    receivedAt: thread.receivedAt,
    sender: thread.sender,
    subject: thread.subject,
    fitScore: classification.fit_score,
    extracted: classification,
    rationale: classification.rationale,
  }

  if (!classification.is_recruiter_outreach) {
    await records.insertTriageRecord({ ...base, category: 'ignore', status: 'ignored' })
    return
  }

  const { category } = classification
  const labelId = await gmail.ensureLabel(CATEGORY_LABELS[category])
  await gmail.applyLabel(threadId, labelId)

  if (category === 'ignore') {
    await records.insertTriageRecord({ ...base, category, status: 'ignored' })
    return
  }

  const draft = draftReply(classification, thread, preferences)
  await records.insertTriageRecord({
    ...base,
    category,
    status: 'drafted',
    draftSubject: draft.subject,
    draftBody: draft.body,
  })
}

// Runs one batch of a sync. `skip` holds thread ids that already failed
// earlier in this same sync, so a thread that keeps failing can't stall it.
// Returns {processed, failed, remaining, lastSyncedAt}; the client calls
// again while remaining > 0.
export async function runSyncBatch({ skip = [], now = () => Date.now() } = {}) {
  if (!(await records.acquireSyncLock())) throw new SyncBusyError('A sync is already running.')
  try {
    const startedAt = now()
    const searchedAt = new Date(startedAt)
    const lastRunAt = await records.getLastRunAt()
    const after = lastRunAt
      ? new Date(lastRunAt)
      : new Date(startedAt - DEFAULT_LOOKBACK_DAYS * 24 * 60 * 60 * 1000)

    const threadIds = await gmail.searchCandidateThreads(GMAIL_SEARCH_QUERY, after)
    const processedIds = await records.getProcessedThreadIds(threadIds)
    const skipIds = new Set(skip)
    const pending = threadIds.filter((id) => !processedIds.has(id) && !skipIds.has(id))

    const preferences = pending.length ? await records.getPreferences() : {}
    let processed = 0
    const failed = []
    for (const threadId of pending) {
      if (processed + failed.length > 0 && now() - startedAt >= BATCH_BUDGET_MS) break
      try {
        await triageThread(threadId, preferences)
        processed++
      } catch (err) {
        console.error(`thread_id=${threadId} failed during triage: ${err.message}`)
        failed.push(threadId)
      }
    }

    const remaining = pending.length - processed - failed.length
    // Only advance the search window once a sync has fully caught up with no
    // failures - otherwise a failed thread from an earlier day could fall
    // outside the next sync's `after:` window and never be retried.
    let lastSyncedAt = lastRunAt
    if (remaining === 0 && failed.length === 0 && skipIds.size === 0) {
      await records.setLastRunAt(searchedAt)
      lastSyncedAt = searchedAt
    }

    return { processed, failed, remaining, lastSyncedAt }
  } finally {
    await records.releaseSyncLock()
  }
}

// Re-renders every still-drafted row in `categories` from the template now
// in effect, so editing a template updates drafts awaiting review right
// away. Pure placeholder substitution from stored fields - no model call.
export async function refreshTemplateDrafts(preferences, categories) {
  if (categories.length === 0) return
  for (const record of await records.getDraftedRecords()) {
    if (!categories.includes(record.category)) continue
    const classification = { ...(record.extracted_json || {}), category: record.category }
    const draft = draftReply(
      classification,
      { sender: record.sender, subject: record.subject },
      preferences
    )
    if (draft) await records.updateDraftText(record.id, draft.subject, draft.body)
  }
}
