// Anthropic model used for both classification and draft generation.
// Overridable so the model can be pinned/rolled back without a code change.
export const ANTHROPIC_MODEL = process.env.ANTHROPIC_MODEL || 'claude-sonnet-5'

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
