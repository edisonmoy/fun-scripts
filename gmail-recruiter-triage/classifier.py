import anthropic

import config

CLASSIFY_TOOL_NAME = "classify_recruiter_email"

# Forced tool-use / structured-output schema. strict=True guarantees the
# response's tool_use.input validates exactly against this schema, so
# main.py never has to free-text-parse a classification out of prose.
CLASSIFY_TOOL = {
    "name": CLASSIFY_TOOL_NAME,
    "description": (
        "Classify one recruiter/job-outreach email thread against Edison's stated "
        "preferences, and extract structured details about the opportunity."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "is_recruiter_outreach": {
                "type": "boolean",
                "description": (
                    "True if this thread is recruiter/job outreach at all, as opposed "
                    "to spam, a newsletter, an existing colleague, a personal email, etc."
                ),
            },
            "category": {
                "type": "string",
                "enum": ["ignore", "keep_warm", "high_interest"],
                "description": (
                    "'ignore' if not recruiter outreach, or not worth any reply. "
                    "'keep_warm' for ordinary recruiter outreach that doesn't match "
                    "target_areas - the default for most recruiter emails. "
                    "'high_interest' only for outreach clearly matching target_areas: "
                    "healthcare AI focused on patient outcomes (not administrative/"
                    "scheduling tooling), climate tech, or venture-studio-style roles."
                ),
            },
            "company": {"type": ["string", "null"]},
            "role": {"type": ["string", "null"]},
            "seniority": {"type": ["string", "null"]},
            "comp": {
                "type": ["string", "null"],
                "description": (
                    "Best-effort compensation figure if mentioned in the email. This "
                    "is LLM-inferred and unreliable - never treat it as authoritative."
                ),
            },
            "location_or_remote": {"type": ["string", "null"]},
            "summary": {
                "type": "string",
                "description": "One-line summary of the opportunity.",
            },
            "rationale": {
                "type": "string",
                "description": (
                    "Why this category was chosen, explicitly referencing the stated "
                    "preferences (target_areas, seniority, comp_floor, etc)."
                ),
            },
        },
        "required": [
            "is_recruiter_outreach",
            "category",
            "company",
            "role",
            "seniority",
            "comp",
            "location_or_remote",
            "summary",
            "rationale",
        ],
        "additionalProperties": False,
    },
}


def _build_system_prompt(preferences):
    return (
        "You are triaging recruiter/job-outreach emails on Edison's behalf. Call the "
        f"{CLASSIFY_TOOL_NAME} tool with your classification of the email thread below "
        "the message.\n\n"
        "Edison's stated preferences:\n"
        f"- Target areas: {preferences.get('target_areas', '')}\n"
        f"- Seniority: {preferences.get('seniority', '')}\n"
        f"- Comp floor: {preferences.get('comp_floor', '')}\n"
        f"- Company excludes: {preferences.get('company_excludes', '')}\n"
        f"- Tone notes: {preferences.get('tone_notes', '')}\n\n"
        "He is specifically interested in healthcare AI focused on patient outcomes "
        "(NOT administrative/scheduling tooling), climate tech, and venture-studio-style "
        "opportunities - these should be 'high_interest'. Ordinary recruiter outreach "
        "outside those areas should be 'keep_warm', not 'high_interest', even if it looks "
        "like a good role in general. Emails that aren't recruiter/job outreach at all "
        "(spam, newsletters, personal email, colleagues, etc.) should have "
        "is_recruiter_outreach=false and category='ignore'. If a company in "
        "company_excludes is the sender, also use category='ignore'."
    )


def classify(thread, preferences, client=None):
    """Classify one email thread via a forced tool call against the Anthropic API.

    `thread` is a dict like {"sender", "subject", "body", ...} as returned
    by gmail_client.get_thread_plaintext(). `preferences` is the dict
    returned by db_client.get_preferences(). Returns a dict matching
    CLASSIFY_TOOL's input schema.

    Note: the returned `comp` field is best-effort and LLM-inferred from
    whatever the email happened to mention - it is not guaranteed accurate
    and should be treated as a hint, not a fact.
    """
    client = client or anthropic.Anthropic()

    user_content = (
        f"Subject: {thread.get('subject', '')}\n"
        f"From: {thread.get('sender', '')}\n\n"
        f"{thread.get('body', '')}"
    )

    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=1024,
        system=_build_system_prompt(preferences),
        tools=[CLASSIFY_TOOL],
        tool_choice={"type": "tool", "name": CLASSIFY_TOOL_NAME},
        messages=[{"role": "user", "content": user_content}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == CLASSIFY_TOOL_NAME:
            return block.input

    raise ValueError("classifier: model did not return a classify_recruiter_email tool call")
