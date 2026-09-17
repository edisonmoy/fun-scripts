import json
import re
from email.utils import parseaddr

import anthropic

import config

# Structured-output schema (output_config.format) so the response is
# guaranteed to be a single parseable JSON object - no free-text parsing.
DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["subject", "body"],
    "additionalProperties": False,
}


DEFAULT_KEEP_WARM_STYLE = (
    "Write a very short reply, exactly three parts and nothing else: "
    "(1) thank them for reaching out, "
    "(2) one sentence commenting on something specific they actually said in "
    "their email (the company, the role, a detail they mentioned - not a "
    "generic compliment), "
    "(3) close with a line like 'Happy to reconnect if things change in the "
    "future.' "
    "Do not say now isn't the right time, do not explain why, do not add "
    "anything beyond those three parts."
)

DEFAULT_HIGH_INTEREST_STYLE = (
    "Write a more substantive reply that shows genuine interest in this "
    "specific opportunity. Ask one clarifying question or request more "
    "information (e.g. more detail on the role's scope, team, or comp) so "
    "the conversation has somewhere concrete to go next."
)

TEMPLATE_PREFERENCE_KEYS = {
    "keep_warm": "keep_warm_template",
    "high_interest": "high_interest_template",
}

# Matches Edison's own placeholder tokens in a custom keep_warm_template,
# e.g. <name>, <company>, <role>. Case-insensitive.
_PLACEHOLDER_PATTERN = re.compile(r"<(\w+)>", re.IGNORECASE)


def _first_name(sender):
    realname, _ = parseaddr(sender or "")
    realname = realname.strip()
    if not realname:
        return None
    return realname.split()[0]


def _fill_template(template, thread, classification):
    """Deterministic placeholder substitution - no LLM involved, so a
    custom template is used exactly as written, verbatim, aside from
    filling in the handful of known tokens.
    """
    values = {
        "name": _first_name(thread.get("sender")) or "there",
        "company": classification.get("company") or "",
        "role": classification.get("role") or "",
    }

    def replace(match):
        key = match.group(1).lower()
        return values.get(key, match.group(0))

    return _PLACEHOLDER_PATTERN.sub(replace, template)


def _build_prompt(classification, thread, preferences):
    if classification.get("category") == "high_interest":
        style = DEFAULT_HIGH_INTEREST_STYLE
    else:
        style = DEFAULT_KEEP_WARM_STYLE

    return (
        "Draft an email reply to the recruiter thread below, on Edison's behalf.\n\n"
        f"{style}\n\n"
        "Critical: your reply MUST reference the SPECIFIC company, role, or other "
        "concrete detail from the email below. Never write a generic template reply - "
        "recruiters can tell immediately, and a generic-sounding reply defeats the "
        "entire purpose of replying at all. Never use placeholder text like [Company], "
        "<role>, or similar under any circumstances - use the real details from the "
        "email, or omit the detail entirely if it truly isn't mentioned.\n\n"
        "Never use an exclamation point anywhere in the reply. Never use an em "
        "dash or en dash - use a period or comma instead.\n\n"
        f"Extracted company: {classification.get('company')}\n"
        f"Extracted role: {classification.get('role')}\n"
        f"Extracted summary: {classification.get('summary')}\n\n"
        "Original email:\n"
        f"Subject: {thread.get('subject', '')}\n"
        f"From: {thread.get('sender', '')}\n\n"
        f"{thread.get('body', '')}\n\n"
        "Return only the reply's subject and body - no commentary."
    )


def generate_draft(classification, thread, preferences, client=None):
    """Generate a reply subject/body for a classified recruiter email.

    `classification` is classifier.classify()'s return value, `thread` is
    gmail_client.get_thread_plaintext()'s return value, `preferences` is
    db_client.get_preferences()'s return value. Returns
    {"subject": str, "body": str}.

    If Edison has set a custom template preference for this category
    (keep_warm_template or high_interest_template), that template is used
    EXACTLY as written (placeholder tokens like <name> filled in
    deterministically) - no LLM call, no rewriting. Only when no custom
    template is set for the category does the model draft a reply from the
    built-in style instructions, in which case the prompt explicitly
    requires referencing the specific company/role/detail from the original
    email - a generic-sounding templated reply is the failure mode to avoid
    there, since recruiters can spot one instantly.
    """
    category = classification.get("category")
    template_key = TEMPLATE_PREFERENCE_KEYS.get(category)
    template = preferences.get(template_key) if template_key else None
    if template:
        return {
            "subject": f"Re: {thread.get('subject', '')}",
            "body": _fill_template(template, thread, classification),
        }

    client = client or anthropic.Anthropic()

    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=1024,
        output_config={"format": {"type": "json_schema", "schema": DRAFT_SCHEMA}},
        messages=[
            {"role": "user", "content": _build_prompt(classification, thread, preferences)}
        ],
    )

    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)
