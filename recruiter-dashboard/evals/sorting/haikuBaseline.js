// Frozen copy of the pre-Jev sorting step: the cheap Haiku pass that
// classified every candidate thread before Jev replaced it (classifier.js
// as of the commit before Jev was added). Kept verbatim so the eval compares
// Jev against exactly what ran in production, not a re-tuned prompt.

import { CLASSIFY_TOOL } from '../../lib/triage/classifier'
import { FAST_MODEL } from '../../lib/triage/config'

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

function quickSystemPrompt(preferences) {
  return (
    "You are triaging recruiter/job-outreach emails on Edison's behalf. Classify " +
    'the email thread in the message.\n\n' +
    preferencesPrompt(preferences) +
    '\n\nJudge from the email text alone. If the company might plausibly be in ' +
    "the target areas but the email is too vague to tell, lean toward a higher " +
    'fit_score so it gets a closer look rather than being dismissed.'
  )
}

// Returns {result, usage} so the eval can price each call. `model` and
// `effort` let the same prompt run on other Claude models for comparison;
// the defaults are exactly the production Haiku call.
export async function haikuQuickClassify(
  thread,
  preferences,
  client,
  { model = FAST_MODEL, effort, maxTokens = 1024 } = {}
) {
  const response = await client.messages.create({
    model,
    max_tokens: maxTokens,
    system: quickSystemPrompt(preferences),
    output_config: {
      format: { type: 'json_schema', schema: CLASSIFY_TOOL.input_schema },
      ...(effort ? { effort } : {}),
    },
    messages: [
      {
        role: 'user',
        content: `Subject: ${thread.subject || ''}\nFrom: ${thread.sender || ''}\n\n${thread.body || ''}`,
      },
    ],
  })
  const text = response.content.find((b) => b.type === 'text')?.text
  if (!text) throw new Error(`no quick result (stop_reason=${response.stop_reason})`)
  return { result: JSON.parse(text), usage: response.usage }
}
