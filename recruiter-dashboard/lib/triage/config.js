// Classification cost tiers. Every email gets one cheap pass with
// FAST_MODEL (no web search); only likely high-interest ones escalate to
// RESEARCH_MODEL with a single web search. Reply text never uses a model -
// see draftWriter.js. Overridable so a model can be pinned without a code
// change.
export const FAST_MODEL = process.env.ANTHROPIC_FAST_MODEL || 'claude-haiku-4-5'
export const RESEARCH_MODEL = process.env.ANTHROPIC_RESEARCH_MODEL || 'claude-sonnet-5'

// A first-pass fit score at or above this (or a high_interest category)
// escalates the email to the research pass.
export const RESEARCH_FIT_THRESHOLD = 60

// Gmail label applied per triage category.
export const CATEGORY_LABELS = {
  keep_warm: 'Recruiter/KeepWarm',
  high_interest: 'Recruiter/HighInterest',
  ignore: 'Recruiter/Ignored',
}

// Gmail search heuristic used to shortlist candidate threads worth sending
// to the classifier. Deliberately broad - the classifier (not this query)
// makes the real recruiter/not-recruiter decision; this just keeps API
// usage down by skipping obviously irrelevant inbox threads.
export const GMAIL_SEARCH_QUERY =
  'in:inbox (recruiter OR hiring OR opportunity OR role OR "reaching out" ' +
  'OR talent OR position OR interview)'

// When there's no prior run_state.last_run_at (first sync ever), how far
// back to search for candidate threads.
export const DEFAULT_LOOKBACK_DAYS = 7
