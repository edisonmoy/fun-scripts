import { parseAddress } from './email'

// Replies are always filled-in templates - no model writes reply text. A
// category uses Edison's own template from preferences when set, else this
// built-in default. Placeholders: <name>, <company>, <role>.
export const DEFAULT_TEMPLATES = {
  keep_warm:
    'Hi <name>,\n\n' +
    'Thank you for reaching out. I am not currently looking for a new role. ' +
    'Happy to connect again in the future when things change.\n\n' +
    'Best,\nEdison',
  high_interest:
    'Hi <name>,\n\n' +
    'Thank you for reaching out. This sounds interesting and I would like to ' +
    'learn more. Could you share more details about the role and the team?\n\n' +
    'Best,\nEdison',
}

export const TEMPLATE_PREFERENCE_KEYS = {
  keep_warm: 'keep_warm_template',
  high_interest: 'high_interest_template',
}

function firstName(sender) {
  const { name } = parseAddress(sender)
  return name ? name.split(/\s+/)[0] : null
}

// Deterministic placeholder substitution (<name>, <company>, <role>,
// case-insensitive), so a template is used exactly as written aside from
// filling in the known tokens.
export function fillTemplate(template, thread, classification) {
  const values = {
    name: firstName(thread.sender) || 'there',
    company: classification.company || '',
    role: classification.role || '',
  }
  return template.replace(/<(\w+)>/g, (match, key) => values[key.toLowerCase()] ?? match)
}

// The template in effect for a category: Edison's own if set, else the
// built-in default. Null for categories that never get a reply (ignore).
export function templateFor(category, preferences) {
  const custom = preferences[TEMPLATE_PREFERENCE_KEYS[category]]
  if (custom && custom.trim()) return custom
  return DEFAULT_TEMPLATES[category] ?? null
}

// {subject, body} for a classified recruiter email, or null if its category
// never gets a reply.
export function draftReply(classification, thread, preferences) {
  const template = templateFor(classification.category, preferences)
  if (!template) return null
  return {
    subject: `Re: ${thread.subject || ''}`,
    body: fillTemplate(template, thread, classification),
  }
}
