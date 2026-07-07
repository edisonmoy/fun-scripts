from unittest.mock import MagicMock, patch

import pytest

import seatgeek_api


def test_client_id_raises_when_missing(monkeypatch):
    monkeypatch.delenv("SEATGEEK_CLIENT_ID", raising=False)

    with pytest.raises(RuntimeError):
        seatgeek_api._client_id()


def test_get_event_stats_parses_response(monkeypatch):
    monkeypatch.setenv("SEATGEEK_CLIENT_ID", "fake-id")
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "id": 18065521,
        "title": "Noah Kahan",
        "datetime_utc": "2026-07-19T22:30:00",
        "venue": {"name": "Citi Field", "city": "Flushing"},
        "url": "https://seatgeek.com/event/18065521",
        "stats": {
            "lowest_price": 500,
            "median_price": 650,
            "average_price": 680,
            "listing_count": 120,
            "visible_listing_count": 100,
        },
    }
    fake_response.raise_for_status = MagicMock()

    with patch("seatgeek_api.requests.get", return_value=fake_response) as mock_get:
        stats = seatgeek_api.get_event_stats(18065521)

    mock_get.assert_called_once()
    assert stats["lowest_price"] == 500
    assert stats["venue"] == "Citi Field"
    assert stats["city"] == "Flushing"


def test_get_tour_events_paginates_until_short_page(monkeypatch):
    monkeypatch.setenv("SEATGEEK_CLIENT_ID", "fake-id")

    page1 = MagicMock()
    page1.json.return_value = {"events": [{"id": i} for i in range(100)]}
    page1.raise_for_status = MagicMock()

    page2 = MagicMock()
    page2.json.return_value = {"events": [{"id": 100}]}
    page2.raise_for_status = MagicMock()

    with patch("seatgeek_api.requests.get", side_effect=[page1, page2]) as mock_get:
        events = seatgeek_api.get_tour_events("noah-kahan", per_page=100)

    assert len(events) == 101
    assert mock_get.call_count == 2


def test_get_tour_events_single_page_when_short(monkeypatch):
    monkeypatch.setenv("SEATGEEK_CLIENT_ID", "fake-id")

    page1 = MagicMock()
    page1.json.return_value = {"events": [{"id": 1}, {"id": 2}]}
    page1.raise_for_status = MagicMock()

    with patch("seatgeek_api.requests.get", return_value=page1) as mock_get:
        events = seatgeek_api.get_tour_events("noah-kahan", per_page=100)

    assert len(events) == 2
    assert mock_get.call_count == 1
