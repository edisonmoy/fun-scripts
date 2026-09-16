from unittest.mock import MagicMock, patch

import pytest

import resy_api


def test_headers_raises_when_credentials_missing(monkeypatch):
    monkeypatch.delenv("RESY_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("RESY_API_KEY", raising=False)
    import config
    monkeypatch.setattr(config, "AUTH_TOKEN", None)
    monkeypatch.setattr(config, "API_KEY", None)

    with pytest.raises(RuntimeError):
        resy_api._headers()


def test_find_venue_returns_first_hit(monkeypatch):
    import config
    monkeypatch.setattr(config, "AUTH_TOKEN", "tok")
    monkeypatch.setattr(config, "API_KEY", "key")

    fake_response = MagicMock()
    fake_response.json.return_value = {
        "search": {
            "hits": [
                {"id": {"resy": 12345}, "name": "Pizza 4P's Brooklyn", "locality": "Brooklyn"},
                {"id": {"resy": 99999}, "name": "Pizza 4P's Manhattan", "locality": "Manhattan"},
            ]
        }
    }
    fake_response.raise_for_status = MagicMock()

    with patch("resy_api.requests.post", return_value=fake_response) as mock_post:
        venue_id = resy_api.find_venue("Pizza 4P's Brooklyn")

    mock_post.assert_called_once()
    assert venue_id == 12345


def test_find_venue_raises_when_no_hits(monkeypatch):
    import config
    monkeypatch.setattr(config, "AUTH_TOKEN", "tok")
    monkeypatch.setattr(config, "API_KEY", "key")

    fake_response = MagicMock()
    fake_response.json.return_value = {"search": {"hits": []}}
    fake_response.raise_for_status = MagicMock()

    with patch("resy_api.requests.post", return_value=fake_response):
        with pytest.raises(LookupError):
            resy_api.find_venue("nonexistent venue")


def test_find_slots_returns_empty_on_404(monkeypatch):
    import config
    monkeypatch.setattr(config, "AUTH_TOKEN", "tok")
    monkeypatch.setattr(config, "API_KEY", "key")

    fake_response = MagicMock()
    fake_response.status_code = 404

    with patch("resy_api.requests.get", return_value=fake_response):
        assert resy_api.find_slots(12345, "2026-09-19", 2) == []


def test_find_slots_returns_slots_list(monkeypatch):
    import config
    monkeypatch.setattr(config, "AUTH_TOKEN", "tok")
    monkeypatch.setattr(config, "API_KEY", "key")

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "results": {"venues": [{"slots": [{"date": {"start": "2026-09-19 19:00:00"}}]}]}
    }
    fake_response.raise_for_status = MagicMock()

    with patch("resy_api.requests.get", return_value=fake_response):
        slots = resy_api.find_slots(12345, "2026-09-19", 2)

    assert len(slots) == 1


def test_slot_time_extracts_hh_mm():
    slot = {"date": {"start": "2026-09-19 19:30:00"}}
    assert resy_api.slot_time(slot) == "19:30"


def test_get_default_payment_method_id_returns_default(monkeypatch):
    import config
    monkeypatch.setattr(config, "AUTH_TOKEN", "tok")
    monkeypatch.setattr(config, "API_KEY", "key")

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "payment_methods": [
            {"id": 111, "is_default": False, "type": "visa", "display": "1111"},
            {"id": 222, "is_default": True, "type": "amex", "display": "1002"},
        ]
    }

    with patch("resy_api.requests.get", return_value=fake_response):
        assert resy_api.get_default_payment_method_id() == 222


def test_get_default_payment_method_id_returns_none_when_no_default(monkeypatch):
    import config
    monkeypatch.setattr(config, "AUTH_TOKEN", "tok")
    monkeypatch.setattr(config, "API_KEY", "key")

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"payment_methods": []}

    with patch("resy_api.requests.get", return_value=fake_response):
        assert resy_api.get_default_payment_method_id() is None


def test_book_sends_given_payment_method_id(monkeypatch):
    import config
    monkeypatch.setattr(config, "AUTH_TOKEN", "tok")
    monkeypatch.setattr(config, "API_KEY", "key")

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"resy_token": "abc"}

    with patch("resy_api.requests.post", return_value=fake_response) as mock_post:
        resy_api.book("book-token-123", payment_method_id=99999999)

    sent_data = mock_post.call_args.kwargs["data"]
    assert sent_data["struct_payment_method"] == '{"id": 99999999}'


def test_book_defaults_to_no_card_on_file(monkeypatch):
    import config
    monkeypatch.setattr(config, "AUTH_TOKEN", "tok")
    monkeypatch.setattr(config, "API_KEY", "key")

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"resy_token": "abc"}

    with patch("resy_api.requests.post", return_value=fake_response) as mock_post:
        resy_api.book("book-token-123")

    sent_data = mock_post.call_args.kwargs["data"]
    assert sent_data["struct_payment_method"] == '{"id": -1}'
