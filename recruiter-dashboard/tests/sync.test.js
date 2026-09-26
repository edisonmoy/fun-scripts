import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/triage/records', () => ({
  acquireSyncLock: vi.fn(),
  releaseSyncLock: vi.fn(),
  getLastRunAt: vi.fn(),
  setLastRunAt: vi.fn(),
  getPreferences: vi.fn(),
  getProcessedThreadIds: vi.fn(),
  insertTriageRecord: vi.fn(),
  getDraftedRecords: vi.fn(),
  updateDraftText: vi.fn(),
  claimForSend: vi.fn(),
  releaseSendClaim: vi.fn(),
}))
vi.mock('../lib/triage/gmail', () => ({
  searchCandidateThreads: vi.fn(),
  getThreadPlaintext: vi.fn(),
  ensureLabel: vi.fn(),
  applyLabel: vi.fn(),
  sendReply: vi.fn(),
}))
vi.mock('../lib/triage/classifier', () => ({ classify: vi.fn() }))

const records = await import('../lib/triage/records')
const gmail = await import('../lib/triage/gmail')
const { classify } = await import('../lib/triage/classifier')
const { BATCH_BUDGET_MS, SyncBusyError, refreshTemplateDrafts, runSyncBatch } = await import(
  '../lib/triage/sync'
)
const { NotSendableError, sendDraft } = await import('../lib/triage/send')

const KEEP_WARM = { is_recruiter_outreach: true, category: 'keep_warm', fit_score: 20, company: 'Acme' }
// A template keeps drafting deterministic - no model call in these tests.
const PREFS = { keep_warm_template: 'Thanks <name>.', high_interest_template: 'Tell me more.' }

beforeEach(() => {
  vi.resetAllMocks()
  vi.spyOn(console, 'error').mockImplementation(() => {})
  records.acquireSyncLock.mockResolvedValue(true)
  records.getLastRunAt.mockResolvedValue(new Date('2026-09-20T00:00:00Z'))
  records.getProcessedThreadIds.mockResolvedValue(new Set())
  records.getPreferences.mockResolvedValue(PREFS)
  gmail.getThreadPlaintext.mockImplementation(async (id) => ({
    sender: 'Jane Doe <jane@co.com>',
    subject: `Subject ${id}`,
    receivedAt: null,
    body: 'Hi',
  }))
  gmail.ensureLabel.mockResolvedValue('label-1')
  classify.mockResolvedValue(KEEP_WARM)
})

describe('runSyncBatch', () => {
  it('refuses to run while another sync holds the lock', async () => {
    records.acquireSyncLock.mockResolvedValue(false)
    await expect(runSyncBatch()).rejects.toBeInstanceOf(SyncBusyError)
    expect(gmail.searchCandidateThreads).not.toHaveBeenCalled()
    expect(records.releaseSyncLock).not.toHaveBeenCalled()
  })

  it('triages only new threads into drafts and never sends', async () => {
    gmail.searchCandidateThreads.mockResolvedValue(['a', 'b', 'c'])
    records.getProcessedThreadIds.mockResolvedValue(new Set(['b']))

    const result = await runSyncBatch()

    expect(result).toMatchObject({ processed: 2, failed: [], remaining: 0 })
    expect(records.insertTriageRecord.mock.calls.map(([r]) => r.threadId)).toEqual(['a', 'c'])
    expect(records.insertTriageRecord.mock.calls[0][0]).toMatchObject({
      category: 'keep_warm',
      status: 'drafted',
      draftSubject: 'Re: Subject a',
      draftBody: 'Thanks Jane.',
    })
    expect(gmail.applyLabel).toHaveBeenCalledWith('a', 'label-1')
    expect(gmail.sendReply).not.toHaveBeenCalled()
    expect(records.releaseSyncLock).toHaveBeenCalledOnce()
  })

  it('records non-recruiter mail as ignored without labeling or drafting', async () => {
    gmail.searchCandidateThreads.mockResolvedValue(['a'])
    classify.mockResolvedValue({ is_recruiter_outreach: false, category: 'ignore' })

    await runSyncBatch()

    expect(gmail.applyLabel).not.toHaveBeenCalled()
    expect(records.insertTriageRecord.mock.calls[0][0]).toMatchObject({
      category: 'ignore',
      status: 'ignored',
    })
  })

  it('labels recruiter mail classified as ignore but does not draft a reply', async () => {
    gmail.searchCandidateThreads.mockResolvedValue(['a'])
    classify.mockResolvedValue({ is_recruiter_outreach: true, category: 'ignore' })

    await runSyncBatch()

    expect(gmail.applyLabel).toHaveBeenCalledOnce()
    const [record] = records.insertTriageRecord.mock.calls[0]
    expect(record).toMatchObject({ category: 'ignore', status: 'ignored' })
    expect(record.draftBody).toBeUndefined()
  })

  it('advances the last-synced time only once fully caught up', async () => {
    gmail.searchCandidateThreads.mockResolvedValue(['a'])
    const result = await runSyncBatch({ now: () => Date.parse('2026-09-26T12:00:00Z') })
    expect(records.setLastRunAt).toHaveBeenCalledWith(new Date('2026-09-26T12:00:00Z'))
    expect(result.lastSyncedAt).toEqual(new Date('2026-09-26T12:00:00Z'))
  })

  it('keeps going past a failing thread and does not advance the window', async () => {
    gmail.searchCandidateThreads.mockResolvedValue(['a', 'b'])
    classify.mockRejectedValueOnce(new Error('boom'))

    const result = await runSyncBatch()

    expect(result).toMatchObject({ processed: 1, failed: ['a'], remaining: 0 })
    expect(records.setLastRunAt).not.toHaveBeenCalled()
  })

  it('skips threads that already failed earlier in the same sync', async () => {
    gmail.searchCandidateThreads.mockResolvedValue(['a', 'b'])

    const result = await runSyncBatch({ skip: ['a'] })

    expect(classify).toHaveBeenCalledOnce()
    expect(result).toMatchObject({ processed: 1, remaining: 0 })
    expect(records.setLastRunAt).not.toHaveBeenCalled()
  })

  it('stops starting new threads once the batch budget is spent', async () => {
    gmail.searchCandidateThreads.mockResolvedValue(['a', 'b', 'c'])
    let clock = 0
    classify.mockImplementation(async () => {
      clock += BATCH_BUDGET_MS
      return KEEP_WARM
    })

    const result = await runSyncBatch({ now: () => clock })

    expect(result).toMatchObject({ processed: 1, remaining: 2 })
    expect(records.setLastRunAt).not.toHaveBeenCalled()
  })

  it('releases the lock when the Gmail search fails', async () => {
    gmail.searchCandidateThreads.mockRejectedValue(new Error('gmail down'))
    await expect(runSyncBatch()).rejects.toThrow('gmail down')
    expect(records.releaseSyncLock).toHaveBeenCalledOnce()
  })
})

describe('refreshTemplateDrafts', () => {
  it('re-renders drafted rows whose category has a template', async () => {
    records.getDraftedRecords.mockResolvedValue([
      { id: 1, category: 'keep_warm', sender: 'Sam Lee <s@co.com>', subject: 'Hi', extracted_json: {} },
      { id: 2, category: 'high_interest', sender: 'x@co.com', subject: 'Yo', extracted_json: {} },
    ])

    await refreshTemplateDrafts({ keep_warm_template: 'Thanks <name>.', high_interest_template: '' })

    expect(records.updateDraftText).toHaveBeenCalledOnce()
    expect(records.updateDraftText).toHaveBeenCalledWith(1, 'Re: Hi', 'Thanks Sam.')
  })
})

describe('sendDraft', () => {
  const ROW = {
    id: 7,
    gmail_thread_id: 't7',
    sender: 'Jane Doe <jane@co.com>',
    draft_subject: 'Re: Role',
    draft_body: 'Thanks.',
  }

  it('sends a claimed row to the bare sender address', async () => {
    records.claimForSend.mockResolvedValue(ROW)
    await sendDraft(7)
    expect(gmail.sendReply).toHaveBeenCalledWith('t7', 'jane@co.com', 'Re: Role', 'Thanks.')
    expect(records.releaseSendClaim).not.toHaveBeenCalled()
  })

  it('does not send a row another request already claimed', async () => {
    records.claimForSend.mockResolvedValue(null)
    await expect(sendDraft(7)).rejects.toBeInstanceOf(NotSendableError)
    expect(gmail.sendReply).not.toHaveBeenCalled()
  })

  it('releases the claim when Gmail rejects the send', async () => {
    records.claimForSend.mockResolvedValue(ROW)
    gmail.sendReply.mockRejectedValue(new Error('Gmail POST failed (500)'))
    await expect(sendDraft(7)).rejects.toThrow('500')
    expect(records.releaseSendClaim).toHaveBeenCalledWith(7)
  })
})
