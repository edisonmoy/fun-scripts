"""Thin client for Resy's private, undocumented consumer API.

Reverse-engineered from browser DevTools traffic - there is no public,
ToS-sanctioned Resy API. Endpoint paths and field names can change without
notice since none of this is documented or versioned for external use.
See README.md for how to grab RESY_AUTH_TOKEN / RESY_API_KEY and for the
ToS risk this carries.
"""
import json
import logging

import requests

import config

logger = logging.getLogger(__name__)

BASE_URL = "https://api.resy.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _headers():
    if not config.AUTH_TOKEN or not config.API_KEY:
        raise RuntimeError(
            "RESY_AUTH_TOKEN and RESY_API_KEY must be set - see README.md "
            "for how to grab them from DevTools."
        )
    return {
        "Authorization": f'ResyAPI api_key="{config.API_KEY}"',
        "X-Resy-Auth-Token": config.AUTH_TOKEN,
        "X-Resy-Universal-Auth": config.AUTH_TOKEN,
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Origin": "https://resy.com",
        "Referer": "https://resy.com/",
        "X-Origin": "https://resy.com",
    }


def find_venue(name):
    """Look up a venue's numeric id by name. Returns the first search hit.

    Resy ranks by relevance, not exact match, so always sanity-check the
    logged name/neighborhood against what you expect before trusting the
    id - especially for chains with multiple locations.
    """
    resp = requests.post(
        f"{BASE_URL}/3/venuesearch/search",
        headers=_headers(),
        json={"query": name, "per_page": 10},
        timeout=10,
    )
    resp.raise_for_status()
    hits = resp.json().get("search", {}).get("hits", [])
    if not hits:
        raise LookupError(f"no Resy venue found for {name!r}")
    hit = hits[0]
    venue_id = hit["id"]["resy"]
    logger.info(
        "resolved venue %r -> id=%s name=%r neighborhood=%r location=%r",
        name, venue_id, hit.get("name"), hit.get("neighborhood"),
        hit.get("location", {}).get("name"),
    )
    return venue_id


def find_slots(venue_id, day, party_size):
    """Return the raw list of available slot dicts for one venue/day/party
    size, or [] if nothing's bookable that day.
    """
    resp = requests.get(
        f"{BASE_URL}/4/find",
        headers=_headers(),
        params={"lat": 0, "long": 0, "day": day, "party_size": party_size, "venue_id": venue_id},
        timeout=10,
    )
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    venues = resp.json().get("results", {}).get("venues", [])
    if not venues:
        return []
    return venues[0].get("slots", [])


def slot_time(slot):
    """Extract the local start time ("HH:MM") from a slot dict."""
    return slot["date"]["start"].split(" ")[1][:5]


def get_book_token(config_id, day, party_size):
    resp = requests.get(
        f"{BASE_URL}/3/details",
        headers=_headers(),
        params={"config_id": config_id, "day": day, "party_size": party_size},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["book_token"]["value"]


def get_default_payment_method_id():
    """Look up the account's default saved card via the (read-only) user
    profile endpoint. Returns None if no payment method is on file - some
    venues book fine with no card ({"id": -1}), but any venue requiring a
    deposit/card-on-file will 402 without a real id.
    """
    resp = requests.get(f"{BASE_URL}/2/user", headers=_headers(), timeout=10)
    resp.raise_for_status()
    for method in resp.json().get("payment_methods", []):
        if method.get("is_default"):
            logger.info(
                "resolved default payment method: id=%s type=%s ending %s",
                method["id"], method.get("type"), method.get("display"),
            )
            return method["id"]
    return None


def book(book_token, payment_method_id=None):
    """Confirm a reservation. This is the one call that actually commits -
    everything above is read-only search/lookup. payment_method_id=None
    books with no card on file ({"id": -1}) - fine for free reservations,
    but a venue requiring a deposit returns 402 without a real id.
    """
    struct_payment_method = {"id": payment_method_id if payment_method_id is not None else -1}
    resp = requests.post(
        f"{BASE_URL}/3/book",
        headers=_headers(),
        data={"book_token": book_token, "struct_payment_method": json.dumps(struct_payment_method)},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()
