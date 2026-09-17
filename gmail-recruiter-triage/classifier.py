import anthropic

import config

CLASSIFY_TOOL_NAME = "classify_recruiter_email"

# Bound on how many pause_turn continuations a single classify() call will
# ride out before giving up - a long research turn shouldn't loop forever.
MAX_RESEARCH_TURNS = 4

# Server-side tool: Anthropic executes the search and injects results into
# the same response, so the model can research the company before it ever
# gets to classify_recruiter_email - no client-side execution needed here.
WEB_SEARCH_TOOL = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 3,
}

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
            "fit_score": {
                "type": "integer",
                "description": (
                    "0-100: how well this opportunity matches Edison's stated "
                    "preferences (target_areas, seniority, comp_floor). Roughly: "
                    "0-39 generic outreach outside target_areas, 40-69 some overlap "
                    "but not a strong match, 70-100 a strong match. Use the full "
                    "range thoughtfully rather than only extremes - this drives a "
                    "visual fit meter, not just the category bucket."
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
                "description": (
                    "One-line summary of the opportunity. If you researched the "
                    "company, ground this in what you actually learned (what they "
                    "build, who they serve), not just what the email itself claims."
                ),
            },
            "rationale": {
                "type": "string",
                "description": (
                    "Why this fit_score/category was chosen, referencing the stated "
                    "preferences (target_areas, seniority, comp_floor, etc). This is "
                    "shown prominently in the dashboard, so keep it to ONE short "
                    "sentence - roughly half the length you'd otherwise default to. "
                    "State the single deciding factor only, not a full walkthrough "
                    "of every preference field. Do NOT state or explain whether this "
                    "is recruiter outreach - that determination is already made via "
                    "is_recruiter_outreach and is not useful to repeat here."
                ),
            },
        },
        "required": [
            "is_recruiter_outreach",
            "category",
            "fit_score",
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
        "'high_interest' is only for outreach that clearly matches the target areas "
        "above. Ordinary recruiter outreach outside those areas should be 'keep_warm', "
        "not 'high_interest', even if it looks like a good role in general - target "
        "areas is the bar, not general attractiveness. Emails that aren't recruiter/job "
        "outreach at all "
        "(spam, newsletters, personal email, colleagues, etc.) should have "
        "is_recruiter_outreach=false and category='ignore'. If a company in "
        "company_excludes is the sender, also use category='ignore'.\n\n"
        "If the email names a company, use the web_search tool to briefly research "
        "what that company actually does (product, industry, mission) before "
        "classifying - an email's own framing of a role can be generic or vague "
        "even when the company itself is a clear match (or a clear non-match) for "
        "the target areas, so don't rely on the email text alone. One or two "
        "searches is usually enough; skip searching entirely if no company name is "
        "identifiable, or if the company is already unambiguous (e.g. a well-known "
        "company you're confident about). Once you've done any research you need, "
        "call classify_recruiter_email with your final assessment."
    )


def _extract_classification(response):
    for block in response.content:
        if block.type == "tool_use" and block.name == CLASSIFY_TOOL_NAME:
            return block.input
    return None


def classify(thread, preferences, client=None):
    """Classify one email thread against the Anthropic API, allowed to use
    web search to research a named company before deciding.

    `thread` is a dict like {"sender", "subject", "body", ...} as returned
    by gmail_client.get_thread_plaintext(). `preferences` is the dict
    returned by db_client.get_preferences(). Returns a dict matching
    CLASSIFY_TOOL's input schema.

    Note: the returned `comp` field is best-effort and LLM-inferred from
    whatever the email happened to mention - it is not guaranteed accurate
    and should be treated as a hint, not a fact.

    Tool choice is deliberately "any" (not forced to classify_recruiter_email
    specifically) so the model is free to call web_search first. If it
    finishes a turn without having called classify_recruiter_email (e.g. it
    only searched and stopped), a single forced follow-up call - tools
    restricted to just classify_recruiter_email - guarantees termination.
    """
    client = client or anthropic.Anthropic()

    user_content = (
        f"Subject: {thread.get('subject', '')}\n"
        f"From: {thread.get('sender', '')}\n\n"
        f"{thread.get('body', '')}"
    )

    system = _build_system_prompt(preferences)
    messages = [{"role": "user", "content": user_content}]

    response = None
    for _ in range(MAX_RESEARCH_TURNS):
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=2048,
            system=system,
            tools=[WEB_SEARCH_TOOL, CLASSIFY_TOOL],
            tool_choice={"type": "any"},
            messages=messages,
        )

        result = _extract_classification(response)
        if result is not None:
            return result

        if getattr(response, "stop_reason", None) == "pause_turn":
            messages = [*messages, {"role": "assistant", "content": response.content}]
            continue

        break

    if response is None:
        raise ValueError("classifier: model did not return a classify_recruiter_email tool call")

    # Model researched/reasoned but didn't call classify - force it on a
    # follow-up turn with only the classify tool available, guaranteeing
    # termination regardless of what happened above.
    messages = [
        *messages,
        {"role": "assistant", "content": response.content},
        {
            "role": "user",
            "content": "Call the classify_recruiter_email tool now with your final assessment.",
        },
    ]
    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=1024,
        system=system,
        tools=[CLASSIFY_TOOL],
        tool_choice={"type": "tool", "name": CLASSIFY_TOOL_NAME},
        messages=messages,
    )
    result = _extract_classification(response)
    if result is not None:
        return result

    raise ValueError("classifier: model did not return a classify_recruiter_email tool call")
