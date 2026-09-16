"""Tests for the MCP layer.

Async tools are driven with anyio.run() rather than a pytest async plugin,
to keep the dev dependencies to what the project already needs.
"""

import anyio
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import config
import mcp_server
import sniper
from resy_api import Booking
from tests.factories import make_details, make_slot


def run(coro):
    return anyio.run(lambda: coro)


def _async_returning(value):
    async def _fn():
        return value

    return _fn


# --- the confirm guard on destructive tools ---------------------------

class _SlotClient:
    """Serves one slot at 19:00 so book_slot has something to find."""

    def find_slots(self, venue_id, day, party_size):
        return [make_slot("19:00")]


def _patch_book(monkeypatch, outcomes):
    """Replace sniper.book_slot with a recorder returning queued outcomes."""
    calls = []

    def fake(client, target, day, slot, live_booking, fee_ceiling=None):
        calls.append({"fee_ceiling": fee_ceiling, "live_booking": live_booking})
        return outcomes[len(calls) - 1]

    monkeypatch.setattr(config.TARGETS[0], "venue_id", 1234)
    monkeypatch.setattr(mcp_server, "_client", _async_returning(_SlotClient()))
    monkeypatch.setattr(mcp_server.sniper, "book_slot", fake)
    monkeypatch.setattr(mcp_server.notify, "notify", lambda outcome: False)
    return calls


def test_free_slot_books_immediately_without_asking(monkeypatch):
    """A free reservation costs the user nothing, so making them approve it
    is friction for its own sake - it should just book."""
    booked = sniper.Outcome(
        sniper.BOOKED,
        config.TARGETS[0],
        day="2026-09-19",
        slot=make_slot("19:00"),
        details=make_details(fee=0.0),
        booking=Booking(resy_token="t", confirmation="ABC123"),
    )
    calls = _patch_book(monkeypatch, [booked])

    result = run(mcp_server.book_slot(day="2026-09-19", time="19:00"))

    assert result["status"] == sniper.BOOKED
    assert result["confirmation"] == "ABC123"
    assert len(calls) == 1  # booked on the first attempt, no round trip to the user


def test_priced_slot_stops_and_reports_the_fee_and_terms(monkeypatch):
    """Anything that puts money on the card is the user's decision."""
    skipped = sniper.Outcome(
        sniper.SKIPPED_FEE,
        config.TARGETS[0],
        day="2026-09-19",
        slot=make_slot("19:00"),
        details=make_details(fee=25.0),
        reason="slot carries a $25.00 cancellation fee",
    )
    calls = _patch_book(monkeypatch, [skipped])

    result = run(mcp_server.book_slot(day="2026-09-19", time="19:00"))

    assert result["status"] == "needs_confirmation"
    assert result["cancellation_fee_usd"] == 25.0
    assert result["cancellation_policy"] == "Cancel 24h ahead"
    assert "Nothing was booked" in result["detail"]
    assert len(calls) == 1  # it stopped; it did not retry behind the user's back


def test_confirming_a_priced_slot_books_it_at_exactly_that_fee(monkeypatch):
    """The user's yes governs that one booking - the standing free-only
    ceiling must not veto a decision they just made with the price in hand."""
    skipped = sniper.Outcome(
        sniper.SKIPPED_FEE,
        config.TARGETS[0],
        day="2026-09-19",
        slot=make_slot("19:00"),
        details=make_details(fee=25.0),
    )
    booked = sniper.Outcome(
        sniper.BOOKED,
        config.TARGETS[0],
        day="2026-09-19",
        slot=make_slot("19:00"),
        details=make_details(fee=25.0),
        booking=Booking(resy_token="t", confirmation="XYZ789"),
    )
    calls = _patch_book(monkeypatch, [skipped, booked])

    result = run(mcp_server.book_slot(day="2026-09-19", time="19:00", confirm=True))

    assert result["status"] == sniper.BOOKED
    assert result["confirmation"] == "XYZ789"
    # Retried with the agreed fee as the ceiling, not the configured $0.
    assert calls[0]["fee_ceiling"] is None
    assert calls[1]["fee_ceiling"] == 25.0


def test_confirm_does_not_widen_the_ceiling_for_a_free_slot(monkeypatch):
    """confirm=True is consulted only when there is something to decide."""
    booked = sniper.Outcome(
        sniper.BOOKED,
        config.TARGETS[0],
        day="2026-09-19",
        slot=make_slot("19:00"),
        details=make_details(fee=0.0),
        booking=Booking(resy_token="t", confirmation="ABC"),
    )
    calls = _patch_book(monkeypatch, [booked])

    run(mcp_server.book_slot(day="2026-09-19", time="19:00", confirm=True))

    assert len(calls) == 1
    assert calls[0]["fee_ceiling"] is None


def test_a_skip_that_is_not_about_money_is_not_treated_as_a_price_question(monkeypatch):
    """SKIPPED_FEE also covers 'no payment method on file', where there is no
    fee to quote and confirming would not help."""
    skipped = sniper.Outcome(
        sniper.SKIPPED_FEE,
        config.TARGETS[0],
        day="2026-09-19",
        slot=make_slot("19:00"),
        details=make_details(fee=0.0, payment_id=None),
        reason="slot requires a payment method but the Resy account has none on file",
    )
    calls = _patch_book(monkeypatch, [skipped])

    result = run(mcp_server.book_slot(day="2026-09-19", time="19:00"))

    assert result["status"] == sniper.SKIPPED_FEE
    assert "payment method" in result["detail"]
    assert len(calls) == 1


def test_cancel_reservation_refuses_without_confirm():
    result = run(mcp_server.cancel_reservation(resy_token="tok"))

    assert result["status"] == "not_cancelled"
    assert "confirm=True is required" in result["detail"]


def test_book_slot_with_confirm_but_no_venue_reports_clearly(monkeypatch):
    monkeypatch.setattr(config.TARGETS[0], "venue_id", 0)
    result = run(mcp_server.book_slot(day="2026-09-19", time="19:00", confirm=True))

    assert result["status"] == "error"
    assert "find_venue" in result["detail"]


def test_book_slot_reports_available_times_when_the_asked_time_is_gone(monkeypatch):
    class Client:
        def find_slots(self, venue_id, day, party_size):
            return [make_slot("18:00"), make_slot("20:30")]

    monkeypatch.setattr(config.TARGETS[0], "venue_id", 1234)
    monkeypatch.setattr(mcp_server, "_client", _async_returning(Client()))

    result = run(mcp_server.book_slot(day="2026-09-19", time="19:00", confirm=True))

    assert result["status"] == "not_available"
    assert result["available_times"] == ["18:00", "20:30"]


# --- credentials and error surfacing ----------------------------------

def test_missing_credentials_raise_a_tool_error_with_the_fix(monkeypatch):
    """A generic 'error executing tool' is useless in a chat - the message
    has to say what to set."""
    def boom():
        raise RuntimeError("RESY_API_KEY and RESY_AUTH_TOKEN must be set.")

    monkeypatch.setattr(mcp_server.runner, "build_client", boom)

    with pytest.raises(ToolError, match="RESY_API_KEY"):
        run(mcp_server._client())


# --- read-only tools ---------------------------------------------------

def test_get_config_reports_guardrails():
    result = run(mcp_server.get_config())

    target = result["targets"][0]
    assert target["weekdays"] == ["Sat"]
    assert target["party_size"] == 2
    assert target["bar_seating_allowed"] is False
    assert result["live_booking_enabled"] is False


def test_upcoming_target_dates_are_all_saturdays():
    from datetime import date

    result = run(mcp_server.upcoming_target_dates(max_dates=4))

    assert len(result["dates"]) == 4
    assert all(date.fromisoformat(d).weekday() == 5 for d in result["dates"])


def test_check_availability_without_venue_id_says_so(monkeypatch):
    monkeypatch.setattr(config.TARGETS[0], "venue_id", 0)
    result = run(mcp_server.check_availability())

    assert "find_venue" in result["error"]


def test_check_availability_marks_slots_that_fail_preferences(monkeypatch):
    class Client:
        def find_slots(self, venue_id, day, party_size):
            # Bar seating only - excluded by default, so nothing is bookable.
            return [make_slot("19:00", config_type="Bar Counter")]

    monkeypatch.setattr(config.TARGETS[0], "venue_id", 1234)
    monkeypatch.setattr(mcp_server, "_client", _async_returning(Client()))

    result = run(mcp_server.check_availability(max_dates=1))

    day = result["dates_with_availability"][0]
    assert day["would_book"] is None
    assert "preferences" in day["note"]


# --- overrides ---------------------------------------------------------

def test_target_for_overrides_only_what_is_passed():
    target = mcp_server._target_for(999, 4, [4, 5], 14)

    assert (target.venue_id, target.party_size) == (999, 4)
    assert target.weekdays == (4, 5)
    assert target.days_ahead == 14
    # Guardrails are never overridable from a tool call.
    assert target.max_cancellation_fee == config.TARGETS[0].max_cancellation_fee
    assert target.allow_bar_seating == config.TARGETS[0].allow_bar_seating


def test_target_for_falls_back_to_config():
    base = config.TARGETS[0]
    target = mcp_server._target_for(None, None, None, None)

    assert target.party_size == base.party_size
    assert target.weekdays == base.weekdays


# --- bearer auth on the remote transport ------------------------------

def _call_middleware(token_header, expected="secret"):
    """Drive the ASGI middleware directly and capture the response."""
    sent = []

    async def inner_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = mcp_server.bearer_auth_middleware(inner_app, expected)
    headers = [(b"authorization", token_header.encode())] if token_header else []
    scope = {"type": "http", "headers": headers}

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b""}

    run(app(scope, receive, send))
    return sent[0]["status"], b"".join(m.get("body", b"") for m in sent)


def test_request_without_a_token_is_rejected():
    status, body = _call_middleware(None)

    assert status == 401
    assert b"unauthorized" in body


def test_request_with_the_wrong_token_is_rejected():
    assert _call_middleware("Bearer wrong")[0] == 401


def test_request_with_a_bare_token_and_no_scheme_is_rejected():
    assert _call_middleware("secret")[0] == 401


def test_request_with_the_right_token_passes_through():
    status, body = _call_middleware("Bearer secret")

    assert status == 200
    assert body == b"ok"


def test_http_transport_refuses_to_start_without_a_token(monkeypatch):
    """An unauthenticated public URL that can book a table is not an option."""
    monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="MCP_BEARER_TOKEN"):
        mcp_server.build_http_app()
