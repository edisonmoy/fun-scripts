import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { classify, needsResearch } from '../lib/triage/classifier'
import { DEFAULT_TEMPLATES, draftReply, fillTemplate, templateFor } from '../lib/triage/draftWriter'

const CLASSIFICATION = {
  is_recruiter_outreach: true,
  category: 'keep_warm',
  fit_score: 20,
  company: 'Acme',
  role: 'Staff Engineer',
  summary: 'Builds rockets',
  rationale: 'Not target areas',
}
const THREAD = { sender: 'Jane Doe <jane@co.com>', subject: 'Opportunity', body: 'Hi Edison' }

function fakeClient(...responses) {
  const create = vi.fn()
  for (const r of responses) create.mockResolvedValueOnce(r)
  return { messages: { create } }
}

const quickResult = (input) => ({
  stop_reason: 'end_turn',
  content: [{ type: 'text', text: JSON.stringify(input) }],
})
const toolUse = (input) => ({
  stop_reason: 'tool_use',
  content: [{ type: 'tool_use', name: 'classify_recruiter_email', input }],
})

describe('fillTemplate', () => {
  it('fills known placeholders case-insensitively and leaves unknown ones', () => {
    expect(fillTemplate('Hi <Name>, re <ROLE> at <company> <other>', THREAD, CLASSIFICATION)).toBe(
      'Hi Jane, re Staff Engineer at Acme <other>'
    )
  })

  it('falls back to "there" when the sender has no display name', () => {
    expect(fillTemplate('Hi <name>', { sender: 'jane@co.com' }, {})).toBe('Hi there')
  })
})

describe('templateFor', () => {
  it("uses Edison's own template when set", () => {
    expect(templateFor('keep_warm', { keep_warm_template: 'Mine' })).toBe('Mine')
  })

  it('falls back to the built-in default when blank', () => {
    expect(templateFor('keep_warm', { keep_warm_template: '  ' })).toBe(DEFAULT_TEMPLATES.keep_warm)
    expect(templateFor('high_interest', {})).toBe(DEFAULT_TEMPLATES.high_interest)
  })

  it('has no template for ignore', () => {
    expect(templateFor('ignore', {})).toBeNull()
  })
})

describe('draftReply', () => {
  it('fills the default template with a Re: subject', () => {
    expect(draftReply(CLASSIFICATION, THREAD, {})).toEqual({
      subject: 'Re: Opportunity',
      body: DEFAULT_TEMPLATES.keep_warm.replace('<name>', 'Jane'),
    })
  })

  it('built-in defaults avoid characters Edison never uses', () => {
    for (const template of Object.values(DEFAULT_TEMPLATES)) {
      expect(template).not.toMatch(/[!—–]/)
    }
  })
})

describe('needsResearch', () => {
  it('escalates likely high-interest recruiter mail only', () => {
    expect(needsResearch({ is_recruiter_outreach: true, category: 'high_interest', fit_score: 10 })).toBe(true)
    expect(needsResearch({ is_recruiter_outreach: true, category: 'keep_warm', fit_score: 60 })).toBe(true)
    expect(needsResearch({ is_recruiter_outreach: true, category: 'keep_warm', fit_score: 59 })).toBe(false)
    expect(needsResearch({ is_recruiter_outreach: false, category: 'ignore', fit_score: 90 })).toBe(false)
  })
})

// Stubs Jev's sorting answers for classify().
function jevFetch({ outreach = 0.97, category = 'keep_warm', fit = 1 } = {}) {
  return vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({
      answers: {
        is_recruiter_outreach: { type: 'noul', noul: outreach },
        category: { type: 'choice', choice: category },
        fit: { type: 'score', score: fit },
      },
    }),
  }))
}

const HIGH_INTEREST = { category: 'high_interest', fit: 4 }

describe('classify', () => {
  beforeEach(() => vi.stubEnv('JEV_API_KEY', 'test-key'))
  afterEach(() => vi.unstubAllEnvs())

  it('never calls an LLM for mail Jev sorts as ignore', async () => {
    const client = fakeClient()
    const fetchImpl = jevFetch({ outreach: 0.02, category: 'keep_warm', fit: 0 })
    await expect(classify(THREAD, {}, { client, fetchImpl })).resolves.toMatchObject({
      is_recruiter_outreach: false,
      category: 'ignore',
      company: null,
    })
    expect(client.messages.create).not.toHaveBeenCalled()
  })

  it("extracts details for ordinary outreach with one cheap pass, keeping Jev's sorting", async () => {
    const client = fakeClient(quickResult({ ...CLASSIFICATION, category: 'high_interest' }))
    await expect(classify(THREAD, {}, { client, fetchImpl: jevFetch() })).resolves.toEqual({
      ...CLASSIFICATION,
      fit_score: 25,
    })

    expect(client.messages.create).toHaveBeenCalledOnce()
    const request = client.messages.create.mock.calls[0][0]
    expect(request.model).toBe('claude-haiku-4-5')
    expect(request.tools).toBeUndefined()
    expect(request.output_config.format.type).toBe('json_schema')
    expect(request.output_config.format.schema.properties).not.toHaveProperty('category')
  })

  it('escalates a likely high-interest email to one research pass that wins', async () => {
    const researched = { ...CLASSIFICATION, category: 'keep_warm', fit_score: 30 }
    const client = fakeClient(toolUse(researched))

    await expect(
      classify(THREAD, {}, { client, fetchImpl: jevFetch(HIGH_INTEREST) })
    ).resolves.toEqual(researched)

    const research = client.messages.create.mock.calls[0][0]
    expect(research.model).toBe('claude-sonnet-5')
    expect(research.tool_choice).toEqual({ type: 'any' })
    const search = research.tools.find((t) => t.name === 'web_search')
    expect(search.max_uses).toBe(1)
  })

  it('resumes a paused research turn', async () => {
    const result = { ...CLASSIFICATION, category: 'high_interest', fit_score: 80 }
    const paused = { stop_reason: 'pause_turn', content: [{ type: 'text', text: 'searching' }] }
    const client = fakeClient(paused, toolUse(result))
    await expect(
      classify(THREAD, {}, { client, fetchImpl: jevFetch(HIGH_INTEREST) })
    ).resolves.toEqual(result)
    const second = client.messages.create.mock.calls[1][0]
    expect(second.messages.at(-1)).toEqual({ role: 'assistant', content: paused.content })
  })

  it('forces the classify tool when research stops without classifying', async () => {
    const result = { ...CLASSIFICATION, category: 'high_interest', fit_score: 80 }
    const stopped = { stop_reason: 'end_turn', content: [{ type: 'text', text: 'done' }] }
    const client = fakeClient(stopped, toolUse(result))
    await expect(
      classify(THREAD, {}, { client, fetchImpl: jevFetch(HIGH_INTEREST) })
    ).resolves.toEqual(result)
    const forced = client.messages.create.mock.calls[1][0]
    expect(forced.tool_choice).toEqual({ type: 'tool', name: 'classify_recruiter_email' })
    expect(forced.tools.map((t) => t.name)).toEqual(['classify_recruiter_email'])
  })

  it("keeps Jev's sorting with extracted details if the research pass fails", async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const client = fakeClient()
    client.messages.create.mockRejectedValueOnce(new Error('overloaded'))
    client.messages.create.mockResolvedValueOnce(quickResult(CLASSIFICATION))
    await expect(
      classify(THREAD, {}, { client, fetchImpl: jevFetch(HIGH_INTEREST) })
    ).resolves.toEqual({ ...CLASSIFICATION, category: 'high_interest', fit_score: 100 })
    expect(client.messages.create.mock.calls[1][0].model).toBe('claude-haiku-4-5')
  })

  it('throws if the extraction pass returns nothing', async () => {
    const client = fakeClient({ stop_reason: 'max_tokens', content: [] })
    await expect(classify(THREAD, {}, { client, fetchImpl: jevFetch() })).rejects.toThrow(
      'no extraction result'
    )
  })

  it('throws if Jev fails, so the thread is retried on the next sync', async () => {
    const client = fakeClient()
    const fetchImpl = vi.fn(async () => ({ ok: false, status: 401 }))
    await expect(classify(THREAD, {}, { client, fetchImpl })).rejects.toThrow('Jev request failed (401)')
    expect(client.messages.create).not.toHaveBeenCalled()
  })
})
