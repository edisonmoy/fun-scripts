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
    # Found on the first turn - no need for the forced-follow-up fallback.
    assert mock_client.messages.create.call_count == 1

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {"type": "any"}
    assert call_kwargs["tools"] == [classifier.WEB_SEARCH_TOOL, classifier.CLASSIFY_TOOL]
    assert call_kwargs["tools"][1]["strict"] is True


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


def test_classify_forces_followup_when_model_searches_without_classifying():
    """Model calls web_search (or just reasons) and stops without ever
    calling classify_recruiter_email - the forced follow-up call (tools
    restricted to just the classify tool) must still produce a result.
    """
    expected = {"is_recruiter_outreach": True, "category": "keep_warm"}
    searched_only = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="Researched the company.")],
        stop_reason="end_turn",
    )
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [searched_only, _tool_use_response(expected)]

    result = classifier.classify({}, {}, client=mock_client)

    assert result == expected
    assert mock_client.messages.create.call_count == 2

    followup_kwargs = mock_client.messages.create.call_args_list[1].kwargs
    assert followup_kwargs["tool_choice"] == {
        "type": "tool",
        "name": classifier.CLASSIFY_TOOL_NAME,
    }
    assert followup_kwargs["tools"] == [classifier.CLASSIFY_TOOL]


def test_classify_continues_through_pause_turn():
    expected = {"is_recruiter_outreach": True, "category": "high_interest"}
    paused = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="still researching...")],
        stop_reason="pause_turn",
    )
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [paused, _tool_use_response(expected)]

    result = classifier.classify({}, {}, client=mock_client)

    assert result == expected
    assert mock_client.messages.create.call_count == 2
    # The paused turn's content must be mirrored back in, not dropped.
    resumed_messages = mock_client.messages.create.call_args_list[1].kwargs["messages"]
    assert any(m.get("content") == paused.content for m in resumed_messages)
