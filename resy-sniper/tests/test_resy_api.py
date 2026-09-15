"""Client tests against canned payloads shaped like the real API responses
documented in karthikvetrivel/resy-sniper's API_DOCUMENTATION.md."""

import json

import pytest

import resy_api
from resy_api import AuthError, RateLimited, ResyClient, ResyError, SlotUnavailable


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or json.dumps(payload or {})
        self.content = self.text.encode()

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.headers = {}
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def build(responses):
    session = FakeSession(responses)
    client = ResyClient("key", "token", min_request_interval=0, session=session)
    return client, session


FIND_PAYLOAD = {
    "results": {
        "venues": [
            {
                "venue": {"id": {"resy": 6194}},
                "slots": [
                    {
                        "date": {"start": "2026-09-19 18:00:00", "end": "2026-09-19 20:00:00"},
                        "config": {
                            "id": 1521664,
                            "type": "Dining Room",
                            "token": (
                                "rgs://resy/6194/1521664/2/2026-09-19"
                                "/2026-09-19/18:00:00/2/Dining Room"
                            ),
                        },
                    },
                    {
                        "date": {"start": "2026-09-19 18:15:00", "end": "2026-09-19 20:15:00"},
                        "config": {"id": 1521665, "type": "Bar Counter", "token": "rgs://x"},
                    },
                ],
            }
        ]
    }
}


def test_auth_headers_are_set_the_way_resy_expects():
    client, session = build([])

    assert session.headers["Authorization"] == 'ResyAPI api_key="key"'
    # Resy requires both auth headers, carrying the same value.
    assert session.headers["X-Resy-Auth-Token"] == "token"
    assert session.headers["X-Resy-Universal-Auth"] == "token"
    assert "resy.com" in session.headers["Origin"]


def test_client_requires_both_credentials():
    with pytest.raises(ValueError):
        ResyClient("", "token")


def test_find_slots_parses_slots():
    client, session = build([FakeResponse(payload=FIND_PAYLOAD)])
    slots = client.find_slots(6194, "2026-09-19", 2)

    assert len(slots) == 2
    assert slots[0].time_str == "6:00 PM"
    assert slots[0].config_type == "Dining Room"
    assert slots[0].token.startswith("rgs://resy/")

    _, url, kwargs = session.calls[0]
    assert url.endswith("/4/find")
    # lat/long are required by the endpoint even when meaningless.
    assert kwargs["params"]["lat"] == 0
    assert kwargs["params"]["venue_id"] == 6194


def test_find_slots_returns_empty_when_sold_out():
    client, _ = build([FakeResponse(payload={"results": {"venues": []}})])
    assert client.find_slots(6194, "2026-09-19", 2) == []


def test_find_slots_skips_malformed_entries():
    payload = {"results": {"venues": [{"slots": [{"config": {}, "date": {}}]}]}}
    client, _ = build([FakeResponse(payload=payload)])
    assert client.find_slots(6194, "2026-09-19", 2) == []


def test_get_booking_details_extracts_token_fee_and_payment_method():
    payload = {
        "book_token": {"value": "real-token", "date_expires": "2026-09-19T23:01:37Z"},
        "user": {
            "payment_methods": [
                {"id": 1, "is_default": False},
                {"id": 2, "is_default": True},
            ]
        },
        "cancellation": {"display_text": "Cancel by 6pm", "fee": {"amount": 25.0}},
    }
    client, session = build([FakeResponse(payload=payload)])
    details = client.get_booking_details("rgs://x", "2026-09-19", 2)

    assert details.book_token == "real-token"
    assert details.default_payment_method_id == 2
    assert details.cancellation_fee == 25.0
    assert details.expires_at is not None

    method, url, kwargs = session.calls[0]
    assert (method, url.endswith("/3/details")) == ("POST", True)
    assert kwargs["json"]["config_id"] == "rgs://x"


def test_details_without_fee_reports_zero():
    payload = {"book_token": {"value": "t"}, "user": {"payment_methods": []}}
    client, _ = build([FakeResponse(payload=payload)])
    details = client.get_booking_details("rgs://x", "2026-09-19", 2)

    assert details.cancellation_fee == 0.0
    assert details.default_payment_method_id is None


def test_details_without_book_token_means_the_slot_went_away():
    client, _ = build([FakeResponse(payload={"message": "Slot is no longer available"})])
    with pytest.raises(SlotUnavailable):
        client.get_booking_details("rgs://x", "2026-09-19", 2)


def test_book_sends_form_encoded_body_with_json_payment_method():
    payload = {"resy_token": "tok", "confirmation": "ABC123"}
    client, session = build([FakeResponse(status_code=201, payload=payload)])
    booking = client.book("book-token", 31876445)

    assert booking.confirmation == "ABC123"
    _, url, kwargs = session.calls[0]
    assert url.endswith("/3/book")
    assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    # struct_payment_method must be a JSON *string* inside the form body.
    assert kwargs["data"]["struct_payment_method"] == '{"id":31876445}'
    assert kwargs["data"]["source_id"] == "resy.com-venue-details"


def test_book_omits_payment_method_when_there_is_none():
    client, session = build([FakeResponse(status_code=201, payload={"resy_token": "t"})])
    client.book("book-token", None)

    assert "struct_payment_method" not in session.calls[0][2]["data"]


def test_book_maps_slot_gone_to_slot_unavailable():
    client, _ = build([FakeResponse(status_code=400, text="Slot is no longer available")])
    with pytest.raises(SlotUnavailable):
        client.book("book-token", 1)


def test_book_maps_invalid_token_to_slot_unavailable():
    client, _ = build([FakeResponse(status_code=400, text="An invalid book token was provided.")])
    with pytest.raises(SlotUnavailable):
        client.book("stale-token", 1)


def test_401_is_reported_as_an_expired_auth_token():
    client, _ = build([FakeResponse(status_code=401, text="unauthorized")])
    with pytest.raises(AuthError, match="45 days"):
        client.find_slots(6194, "2026-09-19", 2)


def test_429_is_reported_as_rate_limiting():
    client, _ = build([FakeResponse(status_code=429, text="slow down")])
    with pytest.raises(RateLimited):
        client.find_slots(6194, "2026-09-19", 2)


def test_other_errors_surface_the_response_body():
    client, _ = build([FakeResponse(status_code=500, text="boom")])
    with pytest.raises(ResyError, match="boom"):
        client.find_slots(6194, "2026-09-19", 2)


def test_search_venues_flattens_hits():
    payload = {
        "search": {
            "hits": [
                {
                    "id": {"resy": 6194},
                    "name": "Carbone",
                    "neighborhood": "Greenwich Village",
                    "locality": "New York",
                },
                {"name": "No ID Here"},
            ]
        }
    }
    client, _ = build([FakeResponse(payload=payload)])
    results = client.search_venues("carbone")

    assert results == [(6194, "Carbone (Greenwich Village, New York)")]


def test_throttle_sleeps_between_requests(monkeypatch):
    slept = []
    monkeypatch.setattr(resy_api.time, "sleep", slept.append)
    session = FakeSession([FakeResponse(payload={}), FakeResponse(payload={})])
    client = ResyClient("k", "t", min_request_interval=0.5, session=session)

    client.reservations()
    client.reservations()

    assert slept and slept[-1] > 0
