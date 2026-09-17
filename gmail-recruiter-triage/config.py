import os

# Anthropic model used for both classification and draft generation.
# Overridable so a run can pin/roll back a model version without a code
# change.
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")

# Quality gate: minimum non-whitespace characters a drafted reply body must
# contain to be considered a real reply rather than a near-empty stub.
MIN_DRAFT_LENGTH = 40

# Substrings that indicate a leftover template placeholder slipped through
# into a drafted reply - any (case-insensitive) match fails the quality
# gate.
PLACEHOLDER_MARKERS = [
    "{{",
    "[INSERT",
    "TODO:",
    "Lorem ipsum",
    "<company>",
    "<role>",
    "<name>",
]

# Punctuation Edison never wants in a drafted reply. Prompted against in
# draft_writer.py too, but enforced here as a deterministic backstop since
# prompt instructions alone aren't guaranteed.
FORBIDDEN_CHARACTERS = ["!", "—", "–"]  # exclamation point, em dash, en dash

# Gmail label applied per triage category.
CATEGORY_LABELS = {
    "keep_warm": "Recruiter/KeepWarm",
    "high_interest": "Recruiter/HighInterest",
    "ignore": "Recruiter/Ignored",
}

# Gmail search heuristic used to shortlist candidate threads worth sending
# to the classifier. Deliberately broad - the classifier (not this query)
# makes the real recruiter/not-recruiter decision; this just keeps API
# usage down by skipping obviously irrelevant inbox threads.
GMAIL_SEARCH_QUERY = (
    'in:inbox (recruiter OR hiring OR opportunity OR role OR "reaching out" '
    "OR talent OR position OR interview)"
)

# When there's no prior run_state.last_run_at (first run ever), how far
# back to search for candidate threads.
DEFAULT_LOOKBACK_DAYS = 7
