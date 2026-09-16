from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import classifier


def _tool_use_response(input_dict):
    block = SimpleNamespace(
        type="tool_use", name=classifier.CLASSIFY_TOOL_NAME, input=input_dict
    )
    return SimpleNamespace(content=[block])


def test_classify_returns_tool_input():
    expected = {
        "is_recruiter_outreach": True,
        "category": "high_interest",
        "company": "Acme Health",
        "role": "ML Engineer",
        "seniority": "Senior",
        "comp": None,
        "location_or_remote": "Remote",
        "summary": "Healthcare AI role focused on patient outcomes.",
        "rationale": "Matches target_areas: healthcare AI / patient outcomes.",
    }
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _tool_use_response(expected)

    thread = {"sender": "a@b.com", "subject": "Great opportunity", "body": "..."}
    preferences = {
        "target_areas": "healthcare AI",
        "seniority": "",
        "comp_floor": None,
        "company_excludes": "",
        "tone_notes": "",
    }

    result = classifier.classify(thread, preferences, client=mock_client)

    assert result == expected

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {
        "type": "tool",
        "name": classifier.CLASSIFY_TOOL_NAME,
    }
    assert call_kwargs["tools"] == [classifier.CLASSIFY_TOOL]
    assert call_kwargs["tools"][0]["strict"] is True


def test_classify_ignores_non_matching_tool_use_blocks():
    expected = {"is_recruiter_outreach": False, "category": "ignore"}
    other_block = SimpleNamespace(type="tool_use", name="some_other_tool", input={"x": 1})
    matching_block = SimpleNamespace(
        type="tool_use", name=classifier.CLASSIFY_TOOL_NAME, input=expected
    )
    mock_client = MagicMock()
    mock_client.messages.create.return_value = SimpleNamespace(
        content=[other_block, matching_block]
    )

    result = classifier.classify({}, {}, client=mock_client)

    assert result == expected


def test_classify_raises_if_no_tool_use_block():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="oops, no tool call")]
    )

    with pytest.raises(ValueError):
        classifier.classify({}, {}, client=mock_client)
