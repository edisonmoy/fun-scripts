import traceback

import alerts
import config
import github_issue
import health
import seatgeek_api
import storage
import supply_demand
from scrapers import stubhub, vividseats


def check_source(namespace, price_per_ticket, event):
    """Log a price reading and return an alert reason if it's a significant drop."""
    if price_per_ticket is None:
        print(f"[{namespace}] no price found this run")
        return None

    floor_before = storage.running_floor(namespace)
    storage.append_record(namespace, {"price_per_ticket": price_per_ticket})
    print(f"[{namespace}] ${price_per_ticket:.0f}/ticket (previous floor: {floor_before})")
    return alerts.check_price_drop(
        namespace, price_per_ticket, floor_before,
        event.price_target_per_ticket, event.pct_drop_threshold,
    )


def check_scraped_source(namespace, scraper, url, event):
    result = scraper.check_price(url)
    consecutive, just_recovered = health.record_outcome(namespace, result["status"])
    print(
        f"[{namespace}] status={result['status']} confidence={result.get('confidence')} "
        f"price={result.get('price_per_ticket')}"
    )

    if result["status"] in ("blocked", "error"):
        if consecutive >= config.ESCALATION_THRESHOLD:
            try:
                github_issue.escalate(namespace, result.get("diagnostic", ""))
                print(f"[{namespace}] escalated to GitHub issue (failed {consecutive}x in a row)")
            except Exception:
                print(f"[{namespace}] failed to escalate to GitHub:")
                traceback.print_exc()
        return None

    if just_recovered:
        try:
            github_issue.resolve(namespace)
            print(f"[{namespace}] recovered - resolved GitHub issue")
        except Exception:
            print(f"[{namespace}] failed to resolve GitHub issue:")
            traceback.print_exc()

    return check_source(namespace, result.get("price_per_ticket"), event)


def process_event(event):
    alert_reasons = []

    # SeatGeek: reliable API, no scraping involved.
    try:
        stats = seatgeek_api.get_event_stats(event.seatgeek_event_id)
        reason = check_source(f"{event.key}__seatgeek", stats["lowest_price"], event)
        if reason:
            alert_reasons.append(reason)
    except Exception:
        print(f"[{event.key}__seatgeek] FAILED:")
        traceback.print_exc()

    # StubHub / Vivid Seats: best-effort scraping, may fail - don't let a
    # failure here block the other sources.
    for site_name, scraper, url in [
        ("stubhub", stubhub, event.stubhub_url),
        ("vividseats", vividseats, event.vividseats_url),
    ]:
        namespace = f"{event.key}__{site_name}"
        try:
            reason = check_scraped_source(namespace, scraper, url, event)
            if reason:
                alert_reasons.append(reason)
        except Exception:
            print(f"[{namespace}] FAILED:")
            traceback.print_exc()

    # Supply/demand signal across the whole tour.
    signal_text = None
    try:
        snapshots = supply_demand.snapshot_tour(event.key, event.seatgeek_performer_slug)
        signal_text = supply_demand.build_signal(event.key, snapshots, event.seatgeek_event_id)
        if signal_text:
            print(f"[{event.key}__supply_demand] {signal_text}")
    except Exception:
        print(f"[{event.key}__supply_demand] FAILED:")
        traceback.print_exc()

    if alert_reasons:
        body_lines = [
            f"{event.name} - {event.date} @ {event.venue}",
            "",
            "Price drop detected:",
            *[f"- {r}" for r in alert_reasons],
            "",
            f"StubHub: {event.stubhub_url}",
            f"SeatGeek: https://seatgeek.com/event/{event.seatgeek_event_id}",
            f"Vivid Seats: {event.vividseats_url}",
        ]
        if signal_text:
            body_lines += ["", "Supply/demand signal:", signal_text]

        alerts.send_email(
            subject=f"{event.name} {event.date} price drop!",
            body="\n".join(body_lines),
        )
        print(f"[{event.key}] Alert email sent.")
    else:
        print(f"[{event.key}] No alert-worthy price drop this run.")


def main():
    for event in config.WATCHED_EVENTS:
        process_event(event)


if __name__ == "__main__":
    main()
