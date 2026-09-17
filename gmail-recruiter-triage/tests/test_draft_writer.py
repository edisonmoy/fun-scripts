from unittest.mock import MagicMock

import draft_writer


def _thread(sender="Dan Bruck <dan@coastalrecruiting.co>", subject="Great opportunity"):
    return {"sender": sender, "subject": subject, "body": "..."}


def test_custom_template_used_verbatim_with_name_filled_in():
    preferences = {"keep_warm_template": "Hi <name>,\n\nThanks for reaching out.\n\nBest,\nEdison"}
    classification = {"category": "keep_warm", "company": "Acme"}
    mock_client = MagicMock()

    result = draft_writer.generate_draft(
        classification, _thread(), preferences, client=mock_client
    )

    assert result["body"] == "Hi Dan,\n\nThanks for reaching out.\n\nBest,\nEdison"
    assert result["subject"] == "Re: Great opportunity"
    # Deterministic substitution - no API call needed at all.
    mock_client.messages.create.assert_not_called()


def test_custom_template_falls_back_to_there_when_no_name_parseable():
    preferences = {"keep_warm_template": "Hi <name>, thanks."}
    classification = {"category": "keep_warm"}
    mock_client = MagicMock()

    result = draft_writer.generate_draft(
        classification, _thread(sender="jobs@company.com"), preferences, client=mock_client
    )

    assert result["body"] == "Hi there, thanks."


def test_custom_template_fills_company_and_role_placeholders():
    preferences = {"keep_warm_template": "Re <company> - <role> role, <name>."}
    classification = {"category": "keep_warm", "company": "Acme Health", "role": "ML Engineer"}
    mock_client = MagicMock()

    result = draft_writer.generate_draft(
        classification, _thread(), preferences, client=mock_client
    )

    assert result["body"] == "Re Acme Health - ML Engineer role, Dan."


def test_no_custom_template_falls_back_to_llm(monkeypatch):
    preferences = {}
    classification = {"category": "keep_warm"}
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(type="text", text='{"subject": "Re: hi", "body": "Thanks."}')]
    )

    result = draft_writer.generate_draft(
        classification, _thread(), preferences, client=mock_client
    )

    assert result == {"subject": "Re: hi", "body": "Thanks."}
    mock_client.messages.create.assert_called_once()


def test_high_interest_ignores_keep_warm_template_and_uses_llm():
    preferences = {"keep_warm_template": "Hi <name>, thanks."}
    classification = {"category": "high_interest"}
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(type="text", text='{"subject": "Re: hi", "body": "Tell me more."}')]
    )

    result = draft_writer.generate_draft(
        classification, _thread(), preferences, client=mock_client
    )

    assert result == {"subject": "Re: hi", "body": "Tell me more."}
    mock_client.messages.create.assert_called_once()


def test_high_interest_template_used_verbatim():
    preferences = {"high_interest_template": "Hi <name>, very interested in <company>."}
    classification = {"category": "high_interest", "company": "Acme Health"}
    mock_client = MagicMock()

    result = draft_writer.generate_draft(
        classification, _thread(), preferences, client=mock_client
    )

    assert result["body"] == "Hi Dan, very interested in Acme Health."
    mock_client.messages.create.assert_not_called()
