import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fitScoreFromLevel, SORT_QUESTIONS, sortThread } from '../lib/triage/jev'

const THREAD = { sender: 'Jane Doe <jane@co.com>', subject: 'Role at Acme', body: 'Hi Edison' }
const PREFS = { target_areas: 'climate tech', company_excludes: 'Initech' }

function jevAnswers({ outreach = 0.97, category = 'keep_warm', fit = 1 } = {}) {
  return {
    model: 'jev-1.13.0',
    answers: {
      is_recruiter_outreach: { type: 'noul', noul: outreach },
      category: { type: 'choice', choice: category, probabilities: {}, confidence: 0.9 },
      fit: { type: 'score', score: fit, legend: {}, probabilities: {}, confidence: 0.8 },
    },
    usage: { input_tokens: 300, output_tokens: 0 },
  }
}

function jsonResponse(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}

beforeEach(() => vi.stubEnv('JEV_API_KEY', 'test-key'))
afterEach(() => vi.unstubAllEnvs())

describe('fitScoreFromLevel', () => {
  it('scales the weighted level onto 0-100', () => {
    expect(fitScoreFromLevel(0)).toBe(0)
    expect(fitScoreFromLevel(2)).toBe(50)
    expect(fitScoreFromLevel(4)).toBe(100)
    expect(fitScoreFromLevel(2.9)).toBe(73)
    expect(fitScoreFromLevel(undefined)).toBe(0)
  })
})

describe('sortThread', () => {
  it('sends the thread and preferences to Jev with the sorting questions', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(jevAnswers({ fit: 3 })))

    const sorted = await sortThread(THREAD, PREFS, fetchImpl)

    expect(sorted).toEqual({ is_recruiter_outreach: true, category: 'keep_warm', fit_score: 75 })
    const [url, init] = fetchImpl.mock.calls[0]
    expect(url).toBe('https://api.typesafe.ai/v1/systemone')
    expect(init.headers.Authorization).toBe('Bearer test-key')
    const body = JSON.parse(init.body)
    expect(body.model).toBe('jev-latest')
    expect(body.questions).toEqual(SORT_QUESTIONS)
    expect(body.state.email).toEqual({ from: THREAD.sender, subject: THREAD.subject, body: THREAD.body })
    expect(body.state.preferences.company_excludes).toBe('Initech')
  })

  it('forces non-outreach to ignore', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(jevAnswers({ outreach: 0.1, category: 'keep_warm' })))
    expect(await sortThread(THREAD, PREFS, fetchImpl)).toMatchObject({
      is_recruiter_outreach: false,
      category: 'ignore',
    })
  })

  it('retries when Jev is overloaded', async () => {
    vi.useFakeTimers()
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({}, 529))
      .mockResolvedValueOnce(jsonResponse(jevAnswers()))
    const pending = sortThread(THREAD, PREFS, fetchImpl)
    await vi.runAllTimersAsync()
    await expect(pending).resolves.toMatchObject({ category: 'keep_warm' })
    expect(fetchImpl).toHaveBeenCalledTimes(2)
    vi.useRealTimers()
  })

  it('does not retry a rejected request', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({}, 401))
    await expect(sortThread(THREAD, PREFS, fetchImpl)).rejects.toThrow('Jev request failed (401)')
    expect(fetchImpl).toHaveBeenCalledOnce()
  })

  it('fails without an API key', async () => {
    vi.stubEnv('JEV_API_KEY', '')
    await expect(sortThread(THREAD, PREFS, vi.fn())).rejects.toThrow('JEV_API_KEY is not set')
  })

  it('rejects a response missing answers', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ answers: {} }))
    await expect(sortThread(THREAD, PREFS, fetchImpl)).rejects.toThrow('missing sorting answers')
  })
})
