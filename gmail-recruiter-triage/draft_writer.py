import json

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


def _style_instructions(category):
    if category == "high_interest":
        return (
            "Write a more substantive reply that shows genuine interest in this "
            "specific opportunity. Ask one clarifying question or request more "
            "information (e.g. more detail on the role's scope, team, or comp) so "
            "the conversation has somewhere concrete to go next."
        )
    return (
        "Write a short, warm, low-commitment reply: thank them for reaching out, say "
        "that now isn't the right time for a move, and ask them to keep Edison in mind "
        "for the future. Keep it brief - this is not the email to get into details."
    )


def _build_prompt(classification, thread, preferences):
    return (
        "Draft an email reply to the recruiter thread below, on Edison's behalf.\n\n"
        f"Tone notes from Edison: {preferences.get('tone_notes', '')}\n\n"
        f"{_style_instructions(classification.get('category'))}\n\n"
        "Critical: your reply MUST reference the SPECIFIC company, role, or other "
        "concrete detail from the email below. Never write a generic template reply - "
        "recruiters can tell immediately, and a generic-sounding reply defeats the "
        "entire purpose of replying at all. Never use placeholder text like [Company], "
        "<role>, or similar under any circumstances - use the real details from the "
        "email, or omit the detail entirely if it truly isn't mentioned.\n\n"
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

    The prompt explicitly requires referencing the specific company/role/
    detail from the original email - a generic-sounding templated reply is
    the failure mode to avoid here, since recruiters can spot one instantly.
    """
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
