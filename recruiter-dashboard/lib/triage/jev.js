// Inbox sorting with Jev, TypeSafe AI's System One model (plain fetch, no
// SDK). Jev never generates text: it answers a fixed set of typed questions
// about a block of state with calibrated probabilities, in one fast, cheap
// call. That makes it a good fit for the sorting decision every candidate
// thread needs (recruiter outreach or not, which category, how good a fit),
// and leaves text extraction to an LLM only for mail worth replying to.

import { JEV_MODEL } from './config'

const API_URL = 'https://api.typesafe.ai/v1/systemone'

// Rate limits (429), overload (529), and gateway errors are transient;
// anything else is a real error.
const RETRY_STATUSES = new Set([429, 500, 502, 503, 504, 529])
const MAX_ATTEMPTS = 3
const REQUEST_TIMEOUT_MS = 15_000

// Ordered fit rubric; the probability-weighted level Jev returns is scaled
// onto the 0-100 fit_score the dashboard and research threshold use.
export const FIT_LEVELS = [
  'Generic outreach, clearly outside the target areas',
  'Mostly outside the target areas, with slight overlap',
  'Some overlap with the target areas, but not a strong match',
  'Good match for the target areas, with a gap in seniority or comp',
  'Strong match for the target areas, seniority, and comp',
]

// Answer keys below double as the question names Jev echoes back.
export const SORT_QUESTIONS = {
  is_recruiter_outreach: {
    type: 'noul',
    instructions:
      'Is `email` recruiter or job outreach addressed to Edison, pitching a role or a ' +
      'hiring conversation?',
    criteria: {
      true: 'A recruiter, founder, or hiring manager reaching out about a job or role',
      false:
        'Spam, a newsletter, a job-board digest, a personal email, an existing ' +
        'colleague, or anything else that is not someone recruiting Edison',
    },
  },
  category: {
    type: 'choice',
    instructions:
      'How should `email` be triaged, judged against `preferences`? If the sender or ' +
      'company is listed in `preferences.company_excludes`, choose ignore.',
    criteria: {
      ignore:
        'Not recruiter outreach, not worth any reply, or from a company in ' +
        'preferences.company_excludes',
      keep_warm:
        'Ordinary recruiter outreach outside preferences.target_areas - the default ' +
        'for most recruiter emails, even for roles that look attractive in general',
      high_interest:
        'Outreach clearly matching preferences.target_areas: healthcare AI focused on ' +
        'patient outcomes (not administrative or scheduling tooling), climate tech, or ' +
        'venture-studio-style roles',
    },
  },
  fit: {
    type: 'score',
    instructions:
      'How well does the opportunity in `email` match `preferences` (target_areas, ' +
      'seniority, comp_floor)? If the company might plausibly be in the target areas ' +
      'but the email is too vague to tell, rate it higher so it gets a closer look.',
    criteria: FIT_LEVELS,
  },
}

function state(thread, preferences) {
  return {
    email: {
      from: thread.sender || '',
      subject: thread.subject || '',
      body: thread.body || '',
    },
    preferences: {
      target_areas: preferences.target_areas ?? '',
      seniority: preferences.seniority ?? '',
      comp_floor: preferences.comp_floor ?? '',
      company_excludes: preferences.company_excludes ?? '',
    },
  }
}

// Jev's score is the probability-weighted mean level index (0..levels-1).
export function fitScoreFromLevel(score, levels = FIT_LEVELS.length) {
  if (typeof score !== 'number' || Number.isNaN(score)) return 0
  const scaled = Math.round((score / (levels - 1)) * 100)
  return Math.min(100, Math.max(0, scaled))
}

async function evaluate(body, fetchImpl) {
  const apiKey = process.env.JEV_API_KEY
  if (!apiKey) throw new Error('JEV_API_KEY is not set')

  for (let attempt = 1; ; attempt++) {
    const res = await fetchImpl(API_URL, {
      method: 'POST',
      headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    })
    if (res.ok) return res.json()
    if (!RETRY_STATUSES.has(res.status) || attempt >= MAX_ATTEMPTS) {
      // Status only - response bodies can echo request content.
      throw new Error(`Jev request failed (${res.status})`)
    }
    await new Promise((resolve) => setTimeout(resolve, 500 * 2 ** (attempt - 1)))
  }
}

// Sorts one thread ({sender, subject, body}) against the preferences row.
// Returns {is_recruiter_outreach, category, fit_score}; non-outreach is
// always category 'ignore'.
export async function sortThread(thread, preferences, fetchImpl = fetch) {
  const data = await evaluate(
    { model: JEV_MODEL, state: state(thread, preferences), questions: SORT_QUESTIONS },
    fetchImpl
  )
  const answers = data?.answers || {}
  const outreach = answers.is_recruiter_outreach?.noul
  const category = answers.category?.choice
  if (typeof outreach !== 'number' || !(category in SORT_QUESTIONS.category.criteria)) {
    throw new Error('Jev response is missing sorting answers')
  }

  const isRecruiterOutreach = outreach >= 0.5
  return {
    is_recruiter_outreach: isRecruiterOutreach,
    category: isRecruiterOutreach ? category : 'ignore',
    fit_score: fitScoreFromLevel(answers.fit?.score),
  }
}
