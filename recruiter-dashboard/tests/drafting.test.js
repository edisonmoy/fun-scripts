import { describe, expect, it, vi } from 'vitest'
import { classify } from '../lib/triage/classifier'
import { fillTemplate, generateDraft, templateDraft } from '../lib/triage/draftWriter'

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

describe('templateDraft', () => {
  it('returns null when the category has no template', () => {
    expect(templateDraft(CLASSIFICATION, THREAD, { keep_warm_template: '' })).toBeNull()
  })

  it('uses the category template verbatim with a Re: subject', () => {
    expect(templateDraft(CLASSIFICATION, THREAD, { keep_warm_template: 'Thanks <name>.' })).toEqual({
      subject: 'Re: Opportunity',
      body: 'Thanks Jane.',
    })
  })
})

describe('generateDraft', () => {
  it('uses the template without calling the model', async () => {
    const client = fakeClient()
    const draft = await generateDraft(CLASSIFICATION, THREAD, { keep_warm_template: 'Hi <name>' }, client)
    expect(draft.body).toBe('Hi Jane')
    expect(client.messages.create).not.toHaveBeenCalled()
  })

  it('asks the model for a structured draft when there is no template', async () => {
    const client = fakeClient({
      stop_reason: 'end_turn',
      content: [{ type: 'text', text: '{"subject":"Re: Opportunity","body":"Thanks."}' }],
    })
    const draft = await generateDraft(CLASSIFICATION, THREAD, {}, client)
    expect(draft).toEqual({ subject: 'Re: Opportunity', body: 'Thanks.' })
    const request = client.messages.create.mock.calls[0][0]
    expect(request.output_config.format.type).toBe('json_schema')
    expect(request.messages[0].content).toContain('Extracted company: Acme')
  })
})

describe('classify', () => {
  it('returns the classify tool input from the first response', async () => {
    const client = fakeClient(toolUse(CLASSIFICATION))
    await expect(classify(THREAD, {}, client)).resolves.toEqual(CLASSIFICATION)
    const request = client.messages.create.mock.calls[0][0]
    expect(request.tool_choice).toEqual({ type: 'any' })
    expect(request.tools.map((t) => t.name)).toEqual(['web_search', 'classify_recruiter_email'])
  })

  it('resumes a paused research turn', async () => {
    const paused = { stop_reason: 'pause_turn', content: [{ type: 'text', text: 'searching' }] }
    const client = fakeClient(paused, toolUse(CLASSIFICATION))
    await expect(classify(THREAD, {}, client)).resolves.toEqual(CLASSIFICATION)
    const second = client.messages.create.mock.calls[1][0]
    expect(second.messages.at(-1)).toEqual({ role: 'assistant', content: paused.content })
  })

  it('forces the classify tool when the model stops without classifying', async () => {
    const stopped = { stop_reason: 'end_turn', content: [{ type: 'text', text: 'done' }] }
    const client = fakeClient(stopped, toolUse(CLASSIFICATION))
    await expect(classify(THREAD, {}, client)).resolves.toEqual(CLASSIFICATION)
    const forced = client.messages.create.mock.calls[1][0]
    expect(forced.tool_choice).toEqual({ type: 'tool', name: 'classify_recruiter_email' })
    expect(forced.tools.map((t) => t.name)).toEqual(['classify_recruiter_email'])
  })

  it('throws if even the forced call does not classify', async () => {
    const stopped = { stop_reason: 'end_turn', content: [{ type: 'text', text: 'no' }] }
    const client = fakeClient(stopped, stopped)
    await expect(classify(THREAD, {}, client)).rejects.toThrow('did not return')
  })
})
