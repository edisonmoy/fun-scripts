import statistics

import config
import seatgeek_api
import storage


def snapshot_tour():
    """Pull current stats for every tour date and log each one's history."""
    events = seatgeek_api.get_tour_events(config.SEATGEEK_PERFORMER_SLUG)
    snapshots = []
    for event in events:
        stats = event.get("stats", {})
        record = {
            "id": event.get("id"),
            "title": event.get("title"),
            "datetime_utc": event.get("datetime_utc"),
            "venue": (event.get("venue") or {}).get("name"),
            "city": (event.get("venue") or {}).get("city"),
            "lowest_price": stats.get("lowest_price"),
            "median_price": stats.get("median_price"),
            "listing_count": stats.get("listing_count"),
        }
        storage.append_record(f"tour_event_{record['id']}", record)
        snapshots.append(record)
    return snapshots


def build_signal(snapshots, target_event_id):
    """Compare the target show against the rest of the tour and its own trend.

    Returns a short human-readable summary, or None if there isn't enough
    data yet to say anything useful.
    """
    target = next((s for s in snapshots if s["id"] == target_event_id), None)
    if target is None or target.get("lowest_price") is None:
        return None

    others = [
        s["lowest_price"] for s in snapshots
        if s["id"] != target_event_id and s.get("lowest_price") is not None
    ]

    lines = [
        f"Tour-wide: {len(snapshots)} dates tracked, "
        f"${target['lowest_price']:.0f}/ticket lowest at {target['venue']}."
    ]

    if others:
        tour_median = statistics.median(others)
        diff_pct = (target["lowest_price"] - tour_median) / tour_median * 100
        direction = "above" if diff_pct > 0 else "below"
        lines.append(
            f"That's {abs(diff_pct):.0f}% {direction} the median lowest price "
            f"(${tour_median:.0f}) across the other {len(others)} tour dates."
        )

    history = storage.load_records(f"tour_event_{target_event_id}")
    price_history = [r["lowest_price"] for r in history if r.get("lowest_price") is not None]
    listing_history = [r["listing_count"] for r in history if r.get("listing_count") is not None]

    if len(price_history) >= 2:
        first, latest = price_history[0], price_history[-1]
        if first:
            pct_change = (latest - first) / first * 100
            trend = "down" if pct_change < 0 else "up"
            lines.append(
                f"Price trend for this show: {trend} {abs(pct_change):.0f}% "
                "since we started tracking."
            )

    if len(listing_history) >= 2:
        first, latest = listing_history[0], listing_history[-1]
        if first:
            pct_change = (latest - first) / first * 100
            trend = (
                "more listings (supply loosening)"
                if pct_change > 0
                else "fewer listings (supply tightening)"
            )
            lines.append(
                f"Inventory trend: {trend}, {abs(pct_change):.0f}% since we started tracking."
            )

    return " ".join(lines)
