"""Tests for the MCP layer.

Async tools are driven with anyio.run() rather than a pytest async plugin,
to keep the dev dependencies to what the project already needs.
"""

import anyio
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import config
import mcp_server
from tests.factories import make_slot


def run(coro):
    return anyio.run(lambda: coro)


# --- the confirm guard on destructive tools ---------------------------

def test_book_slot_refuses_without_confirm():
    """The whole point of the guard: a model calling this tool speculatively
    must not be able to book a table."""
    result = run(mcp_server.book_slot(day="2026-09-19", time="19:00"))

    assert result["status"] == "not_booked"
    assert "confirm=True is required" in result["detail"]


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


def _async_returning(value):
    async def _fn():
        return value

    return _fn


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
