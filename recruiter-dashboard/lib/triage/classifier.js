import Anthropic from '@anthropic-ai/sdk'
import { FAST_MODEL, RESEARCH_FIT_THRESHOLD, RESEARCH_MODEL } from './config'
import { sortThread } from './jev'

export const CLASSIFY_TOOL_NAME = 'classify_recruiter_email'

// Bound on how many pause_turn continuations the research pass will ride
// out before forcing a classification - one search rarely needs more.
const MAX_RESEARCH_TURNS = 2

// Server-side tool: Anthropic executes the search and injects results into
// the same response. Capped at one search: search results are the single
// biggest input-token cost, and one lookup of what the company does is
// enough to confirm or reject a high-interest match.
const WEB_SEARCH_TOOL = {
  type: 'web_search_20260209',
  name: 'web_search',
  max_uses: 1,
}

// Forced tool-use / structured-output schema. strict guarantees the
// response's tool_use.input validates exactly against this schema, so
// nothing downstream has to free-text-parse a classification out of prose.
export const CLASSIFY_TOOL = {
  name: "classify_recruiter_email",
  description: "Classify one recruiter/job-outreach email thread against Edison's stated preferences, and extract structured details about the opportunity.",
  strict: true,
  input_schema: {
    type: "object",
    properties: {
      is_recruiter_outreach: {
        type: "boolean",
        description: "True if this thread is recruiter/job outreach at all, as opposed to spam, a newsletter, an existing colleague, a personal email, etc."
      },
      category: {
        type: "string",
        enum: [
          "ignore",
          "keep_warm",
          "high_interest"
        ],
        description: "'ignore' if not recruiter outreach, or not worth any reply. 'keep_warm' for ordinary recruiter outreach that doesn't match target_areas - the default for most recruiter emails. 'high_interest' only for outreach clearly matching target_areas: healthcare AI focused on patient outcomes (not administrative/scheduling tooling), climate tech, or venture-studio-style roles."
      },
      fit_score: {
        type: "integer",
        description: "0-100: how well this opportunity matches Edison's stated preferences (target_areas, seniority, comp_floor). Roughly: 0-39 generic outreach outside target_areas, 40-69 some overlap but not a strong match, 70-100 a strong match. Use the full range thoughtfully rather than only extremes - this drives a visual fit meter, not just the category bucket."
      },
      company: {
        type: [
          "string",
          "null"
        ]
      },
      role: {
        type: [
          "string",
          "null"
        ]
      },
      seniority: {
        type: [
          "string",
          "null"
        ]
      },
      comp: {
        type: [
          "string",
          "null"
        ],
        description: "Best-effort compensation figure if mentioned in the email. This is LLM-inferred and unreliable - never treat it as authoritative."
      },
      location_or_remote: {
        type: [
          "string",
          "null"
        ]
      },
      summary: {
        type: "string",
        description: "One-line description of what the COMPANY actually does or its mission - e.g. 'Runs AI-driven underwriting for small-business loans' or 'Builds remote patient monitoring for chronic-disease clinics'. This is shown right under the email subject line, so it must not restate or rephrase the subject/role pitch (e.g. don't just repeat 'building the AI operating layer for factories' back if that's already the subject) - say what the company itself does as a business, grounded in what you learned from web_search if you researched it, not the email's own framing of the role. Do not mention the role or job title here at all."
      },
      rationale: {
        type: "string",
        description: "The single deciding factor behind this fit_score/category, as a short phrase (roughly 5-10 words), NOT a full sentence. E.g. 'Fintech back-office tooling, not target areas' or 'Venture-studio structure, strong match'. This is shown prominently in the dashboard next to `summary`, so it must not repeat what `summary` already says about what the company/role is - it only names the fit verdict. Do NOT restate what Edison's target areas/seniority/comp_floor actually are (he already knows his own preferences) and do NOT walk through each preference field one by one - only the deciding factor. Do NOT state or explain whether this is recruiter outreach - that's already captured by is_recruiter_outreach."
      }
    },
    required: [
      "is_recruiter_outreach",
      "category",
      "fit_score",
      "company",
      "role",
      "seniority",
      "comp",
      "location_or_remote",
      "summary",
      "rationale"
    ],
    additionalProperties: false
  }
}

// Fields Jev decides when sorting; everything else in CLASSIFY_TOOL is text
// only an LLM can extract.
const SORT_FIELDS = ['is_recruiter_outreach', 'category', 'fit_score']

// Structured-output schema for the extraction pass: CLASSIFY_TOOL minus the
// sorting fields, which Jev has already answered.
export const EXTRACT_SCHEMA = {
  type: 'object',
  properties: Object.fromEntries(
    Object.entries(CLASSIFY_TOOL.input_schema.properties).filter(
      ([key]) => !SORT_FIELDS.includes(key)
    )
  ),
  required: CLASSIFY_TOOL.input_schema.required.filter((key) => !SORT_FIELDS.includes(key)),
  additionalProperties: false,
}

// Details stored for mail Jev sorts as ignore: no reply is drafted, so no
// LLM call is spent extracting anything.
const NO_DETAILS = {
  company: null,
  role: null,
  seniority: null,
  comp: null,
  location_or_remote: null,
  summary: null,
  rationale: null,
}

function preferencesPrompt(preferences) {
  return (
    "Edison's stated preferences:\n" +
    `- Target areas: ${preferences.target_areas ?? ''}\n` +
    `- Seniority: ${preferences.seniority ?? ''}\n` +
    `- Comp floor: ${preferences.comp_floor ?? ''}\n` +
    `- Company excludes: ${preferences.company_excludes ?? ''}\n\n` +
    "'high_interest' is only for outreach that clearly matches the target areas " +
    "above. Ordinary recruiter outreach outside those areas should be 'keep_warm', " +
    "not 'high_interest', even if it looks like a good role in general - target " +
    "areas is the bar, not general attractiveness. Emails that aren't recruiter/job " +
    'outreach at all ' +
    '(spam, newsletters, personal email, colleagues, etc.) should have ' +
    "is_recruiter_outreach=false and category='ignore'. If a company in " +
    "company_excludes is the sender, also use category='ignore'."
  )
}

// Extraction pass: the sorting decision is already made, so the model only
// pulls out details and names the deciding factor.
function extractSystemPrompt(preferences, sorted) {
  return (
    "You are triaging recruiter/job-outreach emails on Edison's behalf. The email " +
    `thread in the message has already been sorted as category=${sorted.category} ` +
    `with fit_score=${sorted.fit_score} (0-100). Extract the details of the ` +
    'opportunity from the email text alone, and give the rationale for that ' +
    'sorting.\n\n' +
    preferencesPrompt(preferences)
  )
}

// Research pass: may look up what the company actually does.
function researchSystemPrompt(preferences) {
  return (
    "You are triaging recruiter/job-outreach emails on Edison's behalf. Call the " +
    `${CLASSIFY_TOOL_NAME} tool with your classification of the email thread below ` +
    'the message.\n\n' +
    preferencesPrompt(preferences) +
    '\n\nIf the email names a company, you may run one web_search to check what ' +
    "that company actually does (product, industry, mission) - an email's own " +
    'framing of a role can be generic or vague even when the company itself is a ' +
    "clear match (or a clear non-match) for the target areas. Skip searching if no " +
    "company name is identifiable, or if you're already confident what the company " +
    'does. Then call classify_recruiter_email with your final assessment.'
  )
}

function extractClassification(response) {
  const block = response.content.find(
    (b) => b.type === 'tool_use' && b.name === CLASSIFY_TOOL_NAME
  )
  return block ? block.input : null
}

function userMessage(thread) {
  return {
    role: 'user',
    content: `Subject: ${thread.subject || ''}\nFrom: ${thread.sender || ''}\n\n${thread.body || ''}`,
  }
}

// Cheap pass: FAST_MODEL, no tools, structured output against
// EXTRACT_SCHEMA. Jev's sorting fields always win over anything the model
// might echo back.
async function extractDetails(thread, preferences, sorted, client) {
  const response = await client.messages.create({
    model: FAST_MODEL,
    max_tokens: 1024,
    system: extractSystemPrompt(preferences, sorted),
    output_config: { format: { type: 'json_schema', schema: EXTRACT_SCHEMA } },
    messages: [userMessage(thread)],
  })
  const text = response.content.find((b) => b.type === 'text')?.text
  if (!text) throw new Error(`classifier: no extraction result (stop_reason=${response.stop_reason})`)
  return { ...JSON.parse(text), ...sorted }
}

// Research pass: RESEARCH_MODEL with one web search available. tool_choice
// is "any" (not forced to classify_recruiter_email) so the model is free to
// search first; if it stops without classifying, one forced follow-up call
// with only the classify tool available guarantees termination.
async function researchClassify(thread, preferences, client) {
  const system = researchSystemPrompt(preferences)
  let messages = [userMessage(thread)]

  let response = null
  for (let turn = 0; turn < MAX_RESEARCH_TURNS; turn++) {
    response = await client.messages.create({
      model: RESEARCH_MODEL,
      max_tokens: 2048,
      system,
      tools: [WEB_SEARCH_TOOL, CLASSIFY_TOOL],
      tool_choice: { type: 'any' },
      messages,
    })

    const result = extractClassification(response)
    if (result) return result

    if (response.stop_reason === 'pause_turn') {
      messages = [...messages, { role: 'assistant', content: response.content }]
      continue
    }
    break
  }

  messages = [
    ...messages,
    { role: 'assistant', content: response.content },
    {
      role: 'user',
      content: 'Call the classify_recruiter_email tool now with your final assessment.',
    },
  ]
  response = await client.messages.create({
    model: RESEARCH_MODEL,
    max_tokens: 1024,
    system,
    tools: [CLASSIFY_TOOL],
    tool_choice: { type: 'tool', name: CLASSIFY_TOOL_NAME },
    messages,
  })
  const result = extractClassification(response)
  if (result) return result

  throw new Error('classifier: model did not return a classify_recruiter_email tool call')
}

export function needsResearch(sorted) {
  return (
    sorted.is_recruiter_outreach &&
    (sorted.category === 'high_interest' || (sorted.fit_score ?? 0) >= RESEARCH_FIT_THRESHOLD)
  )
}

// Classifies one email thread ({sender, subject, body}) against the
// preferences row. Returns an object matching CLASSIFY_TOOL's input schema;
// its `comp` field is LLM-inferred - a hint, not a fact.
//
// Every email is sorted by Jev (see jev.js), which is far cheaper and
// faster than an LLM. Likely high-interest mail then pays for the research
// pass, whose result replaces Jev's. Other mail that gets a reply gets the
// cheap extraction pass for the details its draft and dashboard row need.
// Mail sorted as ignore never reaches an LLM. If research fails, Jev's
// sorting stands with extracted details rather than losing the email.
export async function classify(thread, preferences, { client, fetchImpl } = {}) {
  const sorted = await sortThread(thread, preferences, fetchImpl)
  const anthropic = () => client ?? (client = new Anthropic())

  if (needsResearch(sorted)) {
    try {
      return await researchClassify(thread, preferences, anthropic())
    } catch (err) {
      console.error(`research pass failed, keeping Jev sorting: ${err.message}`)
    }
  }
  if (sorted.category === 'ignore') return { ...NO_DETAILS, ...sorted }
  return extractDetails(thread, preferences, sorted, anthropic())
}
