import config


def evaluate(body):
    """Check a drafted email body against the quality gate before it's
    allowed to be auto-sent.

    Rejects a draft if the body is empty/whitespace, shorter than
    config.MIN_DRAFT_LENGTH non-whitespace characters, contains any of
    config.PLACEHOLDER_MARKERS (case-insensitive, a sign of a leftover
    template placeholder or a degenerate LLM response), or contains any of
    config.FORBIDDEN_CHARACTERS (Edison never wants exclamation points or
    em/en dashes in a drafted reply).

    Returns (passed: bool, reason: str | None).
    """
    if body is None or not body.strip():
        return False, "body is empty or whitespace-only"

    non_whitespace_length = len("".join(body.split()))
    if non_whitespace_length < config.MIN_DRAFT_LENGTH:
        return False, (
            f"body has only {non_whitespace_length} non-whitespace characters "
            f"(minimum {config.MIN_DRAFT_LENGTH})"
        )

    lowered_body = body.lower()
    for marker in config.PLACEHOLDER_MARKERS:
        if marker.lower() in lowered_body:
            return False, f"body contains placeholder marker: {marker!r}"

    for char in config.FORBIDDEN_CHARACTERS:
        if char in body:
            return False, f"body contains forbidden character: {char!r}"

    return True, None
