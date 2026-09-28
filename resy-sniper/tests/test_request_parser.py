from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

import request_parser
from request_parser import BookingCriteria


def _criteria(**overrides):
    defaults = dict(
        party_size=2,
        days_of_week=["Saturday"],
        time_window_start="17:00",
        time_window_end="21:00",
        lookahead_weeks=8,
        notes="",
    )
    defaults.update(overrides)
    return BookingCriteria(**defaults)


def test_candidate_dates_only_matching_weekday():
    criteria = _criteria(days_of_week=["Saturday"], lookahead_weeks=3)
    dates = criteria.candidate_dates(today=date(2026, 9, 14))  # a Monday
    assert dates == ["2026-09-19", "2026-09-26", "2026-10-03"]


def test_candidate_dates_multiple_weekdays_sorted():
    criteria = _criteria(days_of_week=["Friday", "Saturday"], lookahead_weeks=1)
    dates = criteria.candidate_dates(today=date(2026, 9, 14))  # a Monday
    assert dates == ["2026-09-18", "2026-09-19"]


def test_in_time_window():
    criteria = _criteria(time_window_start="17:00", time_window_end="21:00")
    assert criteria.in_time_window("19:00") is True
    assert criteria.in_time_window("16:59") is False
    assert criteria.in_time_window("21:00") is True
    assert criteria.in_time_window("21:01") is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"time_window_start": "7:00"},  # not zero-padded - breaks string compare
        {"time_window_end": "19:00:00"},
        {"time_window_start": "7pm"},
        {"time_window_end": "24:00"},
        {"time_window_start": "21:00", "time_window_end": "17:00"},  # reversed
        {"party_size": 0},
        {"party_size": 21},
        {"lookahead_weeks": 0},
        {"days_of_week": []},
    ],
)
def test_rejects_criteria_that_would_silently_misbehave(overrides):
    with pytest.raises(ValidationError):
        _criteria(**overrides)


def test_accepts_boundary_values():
    _criteria(time_window_start="00:00", time_window_end="23:59", party_size=20, lookahead_weeks=52)
    _criteria(time_window_start="19:00", time_window_end="19:00", party_size=1, lookahead_weeks=1)


def test_parse_calls_messages_parse_with_expected_shape(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

    fake_criteria = _criteria()
    fake_response = MagicMock()
    fake_response.parsed_output = fake_criteria

    fake_client = MagicMock()
    fake_client.messages.parse.return_value = fake_response

    with patch("request_parser.anthropic.Anthropic", return_value=fake_client):
        result = request_parser.parse("Saturday dinner for 2, flexible 5-9pm")

    assert result is fake_criteria
    call_kwargs = fake_client.messages.parse.call_args.kwargs
    assert call_kwargs["model"] == request_parser.MODEL
    assert call_kwargs["output_format"] is BookingCriteria
    assert call_kwargs["messages"] == [
        {"role": "user", "content": "Saturday dinner for 2, flexible 5-9pm"}
    ]
