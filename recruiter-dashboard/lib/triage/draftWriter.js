import Anthropic from '@anthropic-ai/sdk'
import { ANTHROPIC_MODEL } from './config'
import { parseAddress } from './email'

// Structured-output schema (output_config.format) so the response is
// guaranteed to be a single parseable JSON object - no free-text parsing.
const DRAFT_SCHEMA = {
  type: 'object',
  properties: {
    subject: { type: 'string' },
    body: { type: 'string' },
  },
  required: ['subject', 'body'],
  additionalProperties: false,
}

const DEFAULT_KEEP_WARM_STYLE =
  'Write a very short reply, exactly three parts and nothing else: ' +
  '(1) thank them for reaching out, ' +
  '(2) one sentence commenting on something specific they actually said in ' +
  'their email (the company, the role, a detail they mentioned - not a ' +
  'generic compliment), ' +
  "(3) close with a line like 'Happy to reconnect if things change in the " +
  "future.' " +
  "Do not say now isn't the right time, do not explain why, do not add " +
  'anything beyond those three parts.'

const DEFAULT_HIGH_INTEREST_STYLE =
  'Write a more substantive reply that shows genuine interest in this ' +
  'specific opportunity. Ask one clarifying question or request more ' +
  "information (e.g. more detail on the role's scope, team, or comp) so " +
  'the conversation has somewhere concrete to go next.'

export const TEMPLATE_PREFERENCE_KEYS = {
  keep_warm: 'keep_warm_template',
  high_interest: 'high_interest_template',
}

function firstName(sender) {
  const { name } = parseAddress(sender)
  return name ? name.split(/\s+/)[0] : null
}

// Deterministic placeholder substitution (<name>, <company>, <role>,
// case-insensitive) - no LLM involved, so a custom template is used exactly
// as written aside from filling in the known tokens.
export function fillTemplate(template, thread, classification) {
  const values = {
    name: firstName(thread.sender) || 'there',
    company: classification.company || '',
    role: classification.role || '',
  }
  return template.replace(/<(\w+)>/g, (match, key) => values[key.toLowerCase()] ?? match)
}

// The draft for a category with a custom template configured, or null if
// that category has none.
export function templateDraft(classification, thread, preferences) {
  const key = TEMPLATE_PREFERENCE_KEYS[classification.category]
  const template = key ? preferences[key] : null
  if (!template) return null
  return {
    subject: `Re: ${thread.subject || ''}`,
    body: fillTemplate(template, thread, classification),
  }
}

function buildPrompt(classification, thread) {
  const style =
    classification.category === 'high_interest'
      ? DEFAULT_HIGH_INTEREST_STYLE
      : DEFAULT_KEEP_WARM_STYLE
  const extracted = (value) => value ?? '(not mentioned)'

  return (
    "Draft an email reply to the recruiter thread below, on Edison's behalf.\n\n" +
    `${style}\n\n` +
    'Critical: your reply MUST reference the SPECIFIC company, role, or other ' +
    'concrete detail from the email below. Never write a generic template reply - ' +
    'recruiters can tell immediately, and a generic-sounding reply defeats the ' +
    'entire purpose of replying at all. Never use placeholder text like [Company], ' +
    '<role>, or similar under any circumstances - use the real details from the ' +
    'email, or omit the detail entirely if it truly isn\'t mentioned.\n\n' +
    'Never use an exclamation point anywhere in the reply. Never use an em ' +
    'dash or en dash - use a period or comma instead.\n\n' +
    `Extracted company: ${extracted(classification.company)}\n` +
    `Extracted role: ${extracted(classification.role)}\n` +
    `Extracted summary: ${extracted(classification.summary)}\n\n` +
    'Original email:\n' +
    `Subject: ${thread.subject || ''}\n` +
    `From: ${thread.sender || ''}\n\n` +
    `${thread.body || ''}\n\n` +
    "Return only the reply's subject and body - no commentary."
  )
}

// Generates {subject, body} for a classified recruiter email. A custom
// template for the category is used verbatim (see templateDraft); only
// without one does the model draft a reply from the built-in style, required
// to reference specifics from the email - a generic-sounding reply is the
// failure mode to avoid, since recruiters can spot one instantly.
export async function generateDraft(classification, thread, preferences, client = new Anthropic()) {
  const fromTemplate = templateDraft(classification, thread, preferences)
  if (fromTemplate) return fromTemplate

  const response = await client.messages.create({
    model: ANTHROPIC_MODEL,
    max_tokens: 1024,
    output_config: { format: { type: 'json_schema', schema: DRAFT_SCHEMA } },
    messages: [{ role: 'user', content: buildPrompt(classification, thread) }],
  })
  const text = response.content.find((b) => b.type === 'text')?.text
  if (!text) throw new Error(`draft writer: no text in response (stop_reason=${response.stop_reason})`)
  return JSON.parse(text)
}
