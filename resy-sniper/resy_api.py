"""Thin client for Resy's private (undocumented) API at api.resy.com.

This is NOT an official or partner integration. See the "Terms of service"
section of README.md before using it - Resy's Terms prohibit automated
access, and using this can get your Resy account suspended. Nothing in
this module makes that risk go away.

Endpoint shapes were taken from the reverse-engineered documentation in
karthikvetrivel/resy-sniper and the client in jeffknaide/resy-bot. They
are undocumented and can change without notice: if requests suddenly
start failing, assume Resy changed something rather than that your
credentials are wrong.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.resy.com"

# Resy's web client sends these on every call. Sending obviously-automated
# headers instead is the quickest way to get a key flagged.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://resy.com",
    "Referer": "https://resy.com/",
}


class ResyError(Exception):
    """Any failure talking to Resy."""


class AuthError(ResyError):
    """401 from Resy - auth_token is expired or invalid.

    Resy auth tokens last roughly 45 days, so this is the expected failure
    mode of a long-lived deployment: it will work for weeks and then stop.
    """


class RateLimited(ResyError):
    """429 from Resy - polling too aggressively."""


class SlotUnavailable(ResyError):
    """The slot was taken between finding it and booking it.

    Routine during a drop, not a bug: keep polling.
    """


@dataclass(frozen=True)
class Slot:
    """One bookable time slot from /4/find."""

    start: datetime  # naive local-to-the-restaurant time, as Resy returns it
    end: datetime
    config_id: int
    config_type: str  # "Dining Room", "Bar Counter", "Patio", ...
    token: str  # rgs://... config token; NOT a booking token

    @property
    def time_str(self):
        return self.start.strftime("%-I:%M %p")


@dataclass(frozen=True)
class BookingDetails:
    """Result of /3/details - the step that turns a config token into a
    real, short-lived booking token."""

    book_token: str
    expires_at: datetime | None
    payment_method_ids: list[int]
    default_payment_method_id: int | None
    cancellation_fee: float  # 0.0 when the slot carries no fee
    cancellation_text: str


@dataclass(frozen=True)
class Booking:
    resy_token: str
    confirmation: str


def _parse_resy_datetime(value):
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def _parse_expiry(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class ResyClient:
    """Authenticated Resy API client.

    `min_request_interval` throttles every outbound call (process-wide, via
    a lock) so that a tight polling loop can't accidentally turn into a
    hammer on Resy's API. Keep it non-zero.
    """

    def __init__(self, api_key, auth_token, min_request_interval=0.5, timeout=10, session=None):
        if not api_key or not auth_token:
            raise ValueError("Both api_key and auth_token are required")
        self.min_request_interval = min_request_interval
        self.timeout = timeout
        self._lock = threading.Lock()
        self._last_request_at = 0.0

        self.session = session or requests.Session()
        self.session.headers.update(
            {
                **BROWSER_HEADERS,
                "Authorization": f'ResyAPI api_key="{api_key}"',
                "X-Resy-Auth-Token": auth_token,
                "X-Resy-Universal-Auth": auth_token,
            }
        )

    def _throttle(self):
        with self._lock:
            elapsed = time.monotonic() - self._last_request_at
            wait = self.min_request_interval - elapsed
            if wait > 0:
                time.sleep(wait)
            self._last_request_at = time.monotonic()

    def _request(self, method, path, **kwargs):
        self._throttle()
        url = BASE_URL + path
        try:
            resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise ResyError(f"{method} {path} failed: {exc}") from exc

        if resp.status_code == 401:
            raise AuthError(
                "Resy rejected the auth token (401). Resy tokens expire after "
                "~45 days - grab a fresh X-Resy-Auth-Token from DevTools and "
                "update RESY_AUTH_TOKEN."
            )
        if resp.status_code == 429:
            raise RateLimited("Resy rate-limited this key (429). Back off and slow polling down.")
        if not resp.ok:
            raise ResyError(f"{method} {path} -> {resp.status_code}: {resp.text[:400]}")

        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError as exc:
            raise ResyError(f"{method} {path} returned non-JSON: {resp.text[:200]}") from exc

    def search_venues(self, query):
        """Look up venues by name. Returns [(venue_id, label), ...]."""
        payload = self._request("POST", "/3/venuesearch/search", json={"query": query})
        hits = payload.get("search", {}).get("hits", [])
        results = []
        for hit in hits:
            venue_id = hit.get("id", {}).get("resy")
            if venue_id is None:
                continue
            where = ", ".join(filter(None, [hit.get("neighborhood"), hit.get("locality")]))
            results.append((int(venue_id), f"{hit.get('name', '?')} ({where})"))
        return results

    def find_slots(self, venue_id, day, party_size):
        """Available slots for one venue/day/party size. Empty list = sold out."""
        params = {
            "lat": 0,
            "long": 0,
            "day": day,
            "party_size": party_size,
            "venue_id": venue_id,
        }
        payload = self._request("GET", "/4/find", params=params)
        venues = payload.get("results", {}).get("venues", [])
        if not venues:
            return []

        slots = []
        for raw in venues[0].get("slots", []):
            config = raw.get("config", {})
            date = raw.get("date", {})
            if not config.get("token") or not date.get("start"):
                continue
            slots.append(
                Slot(
                    start=_parse_resy_datetime(date["start"]),
                    end=_parse_resy_datetime(date.get("end", date["start"])),
                    config_id=config.get("id", 0),
                    config_type=config.get("type", "") or "",
                    token=config["token"],
                )
            )
        return slots

    def get_booking_details(self, config_token, day, party_size):
        """Exchange a config token for a real (short-lived) booking token.

        Skipping this step and passing the rgs:// config token straight to
        /3/book always fails with "invalid book token".
        """
        payload = self._request(
            "POST",
            "/3/details",
            json={"config_id": config_token, "day": day, "party_size": party_size},
        )
        book_token = payload.get("book_token", {}).get("value")
        if not book_token:
            raise SlotUnavailable(f"No book_token in /3/details response: {str(payload)[:300]}")

        methods = payload.get("user", {}).get("payment_methods", []) or []
        default = next((m["id"] for m in methods if m.get("is_default")), None)
        if default is None and methods:
            default = methods[0].get("id")

        cancellation = payload.get("cancellation") or {}
        fee = ((cancellation.get("fee") or {}).get("amount")) or 0

        return BookingDetails(
            book_token=book_token,
            expires_at=_parse_expiry(payload.get("book_token", {}).get("date_expires")),
            payment_method_ids=[m["id"] for m in methods if m.get("id") is not None],
            default_payment_method_id=default,
            cancellation_fee=float(fee),
            cancellation_text=cancellation.get("display_text", "") or "",
        )

    def book(self, book_token, payment_method_id=None):
        """Commit the booking. This charges nothing up front, but it can put
        a real cancellation fee on the card attached to the Resy account."""
        form = {
            "book_token": book_token,
            "source_id": "resy.com-venue-details",
            "venue_marketing_opt_in": 0,
        }
        if payment_method_id is not None:
            # Must be a JSON *string* inside form-encoded data, not a nested dict.
            form["struct_payment_method"] = json.dumps(
                {"id": payment_method_id}, separators=(",", ":")
            )

        try:
            payload = self._request(
                "POST",
                "/3/book",
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except ResyError as exc:
            text = str(exc).lower()
            if "no longer available" in text or "invalid book token" in text:
                raise SlotUnavailable(str(exc)) from exc
            raise

        token = payload.get("resy_token")
        if not token:
            raise ResyError(f"Book call returned no resy_token: {str(payload)[:300]}")
        return Booking(resy_token=token, confirmation=payload.get("confirmation", "") or "")

    def reservations(self, limit=20):
        """The account's upcoming reservations. Used as the double-booking guard."""
        payload = self._request("GET", "/3/user/reservations", params={"limit": limit})
        return payload.get("reservations", []) or []
