import quality_gate


def test_empty_body_fails():
    passed, reason = quality_gate.evaluate("")
    assert not passed
    assert reason


def test_none_body_fails():
    passed, reason = quality_gate.evaluate(None)
    assert not passed
    assert reason


def test_whitespace_only_body_fails():
    passed, reason = quality_gate.evaluate("   \n\t  ")
    assert not passed
    assert reason


def test_short_body_fails():
    passed, reason = quality_gate.evaluate("Thanks, not interested.")
    assert not passed
    assert "characters" in reason


def test_placeholder_marker_fails():
    body = (
        "Hi [INSERT NAME], thanks so much for reaching out about the exciting "
        "opportunity at your company - really appreciate you thinking of me!"
    )
    passed, reason = quality_gate.evaluate(body)
    assert not passed
    assert "placeholder" in reason


def test_placeholder_marker_is_case_insensitive():
    body = (
        "hi there, thanks for reaching out! todo: figure out what to actually say "
        "here before sending this reply back to them, but not right now anyway."
    )
    passed, reason = quality_gate.evaluate(body)
    assert not passed
    assert "placeholder" in reason


def test_valid_body_passes():
    body = (
        "Hi Jane, thanks so much for reaching out about the Staff ML Engineer role "
        "at Acme Health. It's not the right time for me to make a move, but I'd love "
        "to stay in touch - please keep me in mind for anything similar down the line!"
    )
    passed, reason = quality_gate.evaluate(body)
    assert passed
    assert reason is None
