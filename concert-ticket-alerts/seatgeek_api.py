import os

import requests

BASE_URL = "https://api.seatgeek.com/2"


def _client_id():
    client_id = os.environ.get("SEATGEEK_CLIENT_ID")
    if not client_id:
        raise RuntimeError("SEATGEEK_CLIENT_ID environment variable is not set")
    return client_id


def get_event_stats(event_id):
    """Lowest/median/average price and listing counts for one event."""
    resp = requests.get(
        f"{BASE_URL}/events/{event_id}",
        params={"client_id": _client_id()},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    stats = data.get("stats", {})
    return {
        "id": data.get("id"),
        "title": data.get("title"),
        "datetime_utc": data.get("datetime_utc"),
        "venue": (data.get("venue") or {}).get("name"),
        "city": (data.get("venue") or {}).get("city"),
        "url": data.get("url"),
        "lowest_price": stats.get("lowest_price"),
        "median_price": stats.get("median_price"),
        "average_price": stats.get("average_price"),
        "listing_count": stats.get("listing_count"),
        "visible_listing_count": stats.get("visible_listing_count"),
    }


def get_tour_events(performer_slug, per_page=100):
    """All events for a performer, e.g. every date on the tour."""
    events = []
    page = 1
    while True:
        resp = requests.get(
            f"{BASE_URL}/events",
            params={
                "performers.slug": performer_slug,
                "client_id": _client_id(),
                "per_page": per_page,
                "page": page,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("events", [])
        events.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    return events
