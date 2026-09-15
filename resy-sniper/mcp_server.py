"""MCP server exposing the Resy sniper as tools, so it can be driven from a
Claude conversation via a custom connector.

Two transports, same tools:

  python mcp_server.py                      # stdio, for a local MCP client
  python mcp_server.py --transport http     # streamable HTTP, for a remote
                                            # custom connector

The same Terms-of-Service caveat in README.md applies to everything here -
wrapping the calls in MCP tools doesn't make automated Resy access permitted.

Safety note: these tools are reachable by a model. Read-only tools are
annotated as such; the two that spend something real (`book_slot`,
`cancel_reservation`) require an explicit `confirm=True` argument *and*
still honour every guardrail in config.py, so an over-eager tool call
can't book a table or drop one on its own.
"""

import argparse
import hmac
import logging
import os
import sys
from datetime import date as date_cls

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

import config
import notify
import runner
import sniper
from resy_api import ResyError

logger = logging.getLogger(__name__)

mcp = MCPServer(
    name="resy-sniper",
    version="1.0.0",
    instructions=(
        "Watches Resy for restaurant reservations and books them. "
        "Use check_availability to see what's open before booking. "
        "book_slot and cancel_reservation take real, irreversible actions on "
        "the user's Resy account and require confirm=True - always show the "
        "user the exact date, time and cancellation policy and get their "
        "agreement before calling either."
    ),
)

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False)
DESTRUCTIVE = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=False
)


async def _client():
    """Build a Resy client off the event loop (the HTTP layer is sync)."""
    try:
        return await anyio.to_thread.run_sync(runner.build_client)
    except RuntimeError as exc:
        # ToolError's message reaches the client; anything else is reported
        # as a bare "error executing tool", which is useless in a chat.
        raise ToolError(str(exc)) from exc


async def _call(fn, *args):
    """Run a blocking Resy call in a worker thread, surfacing why it failed."""
    try:
        return await anyio.to_thread.run_sync(fn, *args)
    except (ResyError, RuntimeError) as exc:
        raise ToolError(f"{type(exc).__name__}: {exc}") from exc


def _target_for(venue_id, party_size, weekdays, days_ahead):
    """An ad-hoc Target so one-off tool calls can override the configured one."""
    base = config.TARGETS[0]
    return config.Target(
        key=base.key,
        name=base.name,
        venue_id=venue_id or base.venue_id,
        party_size=party_size or base.party_size,
        weekdays=tuple(weekdays) if weekdays else base.weekdays,
        days_ahead=days_ahead or base.days_ahead,
        preferred_start=base.preferred_start,
        preferred_end=base.preferred_end,
        acceptable_start=base.acceptable_start,
        acceptable_end=base.acceptable_end,
        allow_bar_seating=base.allow_bar_seating,
        max_cancellation_fee=base.max_cancellation_fee,
    )


@mcp.tool(
    description="Show the configured restaurant target and the safety guardrails "
    "currently in effect, including whether live booking is enabled.",
    annotations=READ_ONLY,
)
async def get_config() -> dict:
    targets = [
        {
            "key": t.key,
            "name": t.name,
            "venue_id": t.venue_id or None,
            "party_size": t.party_size,
            "weekdays": [
                ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d] for d in t.weekdays
            ],
            "preferred_window": f"{t.preferred_start:%H:%M}-{t.preferred_end:%H:%M}",
            "acceptable_window": f"{t.acceptable_start:%H:%M}-{t.acceptable_end:%H:%M}",
            "bar_seating_allowed": t.allow_bar_seating,
            "max_cancellation_fee_usd": t.max_cancellation_fee,
        }
        for t in config.TARGETS
    ]
    return {
        "targets": targets,
        "live_booking_enabled": config.LIVE_BOOKING,
        "email_configured": notify.is_configured(),
        "note": (
            "live_booking_enabled=false means run_snipe will only report what it "
            "would have booked. book_slot can still book when called with confirm=True."
        ),
    }


@mcp.tool(
    description="Look up a restaurant's numeric Resy venue ID by name. "
    "Needed before checking availability at a new restaurant.",
    annotations=READ_ONLY,
)
async def find_venue(query: str) -> dict:
    client = await _client()
    results = await _call(client.search_venues, query)
    return {"matches": [{"venue_id": vid, "name": label} for vid, label in results]}


@mcp.tool(
    description="List open reservation slots for upcoming target dates. Read-only - "
    "books nothing. Shows which slot the sniper would pick and why others are skipped.",
    annotations=READ_ONLY,
)
async def check_availability(
    venue_id: int | None = None,
    party_size: int | None = None,
    days_ahead: int | None = None,
    weekdays: list[int] | None = None,
    max_dates: int = 8,
) -> dict:
    """weekdays uses Python ints: Monday=0 ... Sunday=6. Omit to use the config."""
    target = _target_for(venue_id, party_size, weekdays, days_ahead)
    if not target.venue_id:
        return {"error": "No venue_id set. Call find_venue first."}

    client = await _client()
    days = []
    for day in sniper.target_dates(target)[:max_dates]:
        slots = await _call(client.find_slots, target.venue_id, day, target.party_size)
        if not slots:
            continue
        ranked = sniper.rank_slots(target, slots)
        days.append(
            {
                "date": day,
                "all_slots": [
                    {"time": s.time_str, "seating": s.config_type or "unspecified"}
                    for s in slots
                ],
                "would_book": (
                    {"time": ranked[0].time_str, "seating": ranked[0].config_type}
                    if ranked
                    else None
                ),
                "note": None if ranked else "no slot matches your time/seating preferences",
            }
        )

    return {
        "venue_id": target.venue_id,
        "party_size": target.party_size,
        "dates_with_availability": days,
        "summary": f"{len(days)} of the next {max_dates} target dates have openings",
    }


@mcp.tool(
    description="Run one snipe pass: scan target dates and book the best matching slot. "
    "Respects the live-booking setting - set dry_run=false AND have live booking enabled "
    "to actually book. Emails a confirmation on success.",
    annotations=DESTRUCTIVE,
)
async def run_snipe(dry_run: bool = True) -> dict:
    live = config.LIVE_BOOKING and not dry_run
    client = await _client()
    outcomes = await _call(
        lambda: runner.run_once(client=client, live_booking=live, send_email=True)
    )
    return {
        "live_booking": live,
        "results": [
            {
                "target": o.target.key,
                "status": o.status,
                "date": o.day,
                "time": o.slot.time_str if o.slot else None,
                "seating": o.slot.config_type if o.slot else None,
                "confirmation": o.booking.confirmation if o.booking else None,
                "detail": o.reason,
            }
            for o in outcomes
        ],
    }


@mcp.tool(
    description="Book one specific slot by date and time. Irreversible and may commit "
    "the user to a cancellation fee. Requires confirm=True. Show the user the exact "
    "date, time and fee first.",
    annotations=DESTRUCTIVE,
)
async def book_slot(
    day: str,
    time: str,
    confirm: bool = False,
    venue_id: int | None = None,
    party_size: int | None = None,
) -> dict:
    """day is YYYY-MM-DD, time is 24-hour HH:MM as shown by check_availability."""
    if not confirm:
        return {
            "status": "not_booked",
            "detail": "confirm=True is required. Nothing was booked.",
        }

    target = _target_for(venue_id, party_size, None, None)
    if not target.venue_id:
        return {"status": "error", "detail": "No venue_id set. Call find_venue first."}

    client = await _client()
    slots = await _call(client.find_slots, target.venue_id, day, target.party_size)
    wanted = [s for s in slots if s.start.strftime("%H:%M") == time]
    if not wanted:
        return {
            "status": "not_available",
            "detail": f"No slot at {time} on {day}.",
            "available_times": sorted(s.start.strftime("%H:%M") for s in slots),
        }

    outcome = await _call(sniper.book_slot, client, target, day, wanted[0], True)
    await _call(notify.notify, outcome)
    return {
        "status": outcome.status,
        "date": day,
        "time": wanted[0].time_str,
        "seating": wanted[0].config_type,
        "confirmation": outcome.booking.confirmation if outcome.booking else None,
        "cancellation_policy": (
            outcome.details.cancellation_text if outcome.details else None
        ),
        "detail": outcome.reason,
    }


@mcp.tool(
    description="List the Resy account's upcoming reservations.",
    annotations=READ_ONLY,
)
async def list_reservations(limit: int = 20) -> dict:
    client = await _client()
    raw = await _call(client.reservations, limit)
    return {"count": len(raw), "reservations": raw}


@mcp.tool(
    description="Cancel a reservation by its resy_token (from list_reservations). "
    "Irreversible - the table returns to the pool and any cancellation fee applies. "
    "Requires confirm=True.",
    annotations=DESTRUCTIVE,
)
async def cancel_reservation(resy_token: str, confirm: bool = False) -> dict:
    if not confirm:
        return {
            "status": "not_cancelled",
            "detail": "confirm=True is required. Nothing was cancelled.",
        }
    client = await _client()
    try:
        await _call(client.cancel, resy_token)
    except ResyError as exc:
        return {"status": "error", "detail": str(exc)}
    return {"status": "cancelled", "detail": "Resy will email its own confirmation."}


@mcp.tool(
    description="The dates the sniper is currently watching, soonest first.",
    annotations=READ_ONLY,
)
async def upcoming_target_dates(max_dates: int = 10) -> dict:
    target = config.TARGETS[0]
    days = sniper.target_dates(target, today=date_cls.today())[:max_dates]
    return {"target": target.name, "dates": days}


# --- remote transport ---------------------------------------------------

def bearer_auth_middleware(app, expected_token):
    """Reject any request without the right bearer token.

    This server can book a table, so an unauthenticated public URL is not an
    option. Compared with constant time so the token can't be guessed by
    timing the response.
    """

    async def middleware(scope, receive, send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        presented = headers.get(b"authorization", b"").decode()
        if not hmac.compare_digest(presented, f"Bearer {expected_token}"):
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
            return

        await app(scope, receive, send)

    return middleware


def build_http_app():
    """Starlette app serving MCP over streamable HTTP at /mcp."""
    token = os.environ.get("MCP_BEARER_TOKEN")
    if not token:
        raise RuntimeError(
            "MCP_BEARER_TOKEN must be set for the HTTP transport - this server "
            "can book reservations, so it must not be exposed unauthenticated."
        )
    app = mcp.streamable_http_app(streamable_http_path="/mcp", host="0.0.0.0")
    return bearer_auth_middleware(app, token)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Resy sniper MCP server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8080)))
    args = parser.parse_args(argv)

    # stdio speaks MCP on stdout - logs must go to stderr or they corrupt it.
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return 0

    import uvicorn

    uvicorn.run(build_http_app(), host="0.0.0.0", port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
