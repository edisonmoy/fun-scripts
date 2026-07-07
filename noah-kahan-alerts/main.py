import traceback

import alerts
import config
import seatgeek_api
import storage
import supply_demand
from scrapers import stubhub, vividseats


def check_source(name, price_per_ticket):
    """Log a price reading and return an alert reason if it's a significant drop."""
    if price_per_ticket is None:
        print(f"[{name}] no price found this run")
        return None

    floor_before = storage.running_floor(name)
    storage.append_record(name, {"price_per_ticket": price_per_ticket})
    print(f"[{name}] ${price_per_ticket:.0f}/ticket (previous floor: {floor_before})")
    return alerts.check_price_drop(name, price_per_ticket, floor_before)


def main():
    alert_reasons = []

    # SeatGeek: reliable API, no scraping involved.
    try:
        stats = seatgeek_api.get_event_stats(config.SEATGEEK_EVENT_ID)
        reason = check_source("seatgeek", stats["lowest_price"])
        if reason:
            alert_reasons.append(reason)
    except Exception:
        print("[seatgeek] FAILED:")
        traceback.print_exc()

    # StubHub / Vivid Seats: best-effort scraping, may fail - don't let a
    # failure here block the other sources.
    for name, scraper, url in [
        ("stubhub", stubhub, config.STUBHUB_URL),
        ("vividseats", vividseats, config.VIVIDSEATS_URL),
    ]:
        try:
            price = scraper.get_lowest_price_per_ticket(url)
            reason = check_source(name, price)
            if reason:
                alert_reasons.append(reason)
        except Exception:
            print(f"[{name}] FAILED (scraper likely needs updating - see README):")
            traceback.print_exc()

    # Supply/demand signal across the whole tour.
    signal_text = None
    try:
        snapshots = supply_demand.snapshot_tour()
        signal_text = supply_demand.build_signal(snapshots, config.SEATGEEK_EVENT_ID)
        if signal_text:
            print(f"[supply/demand] {signal_text}")
    except Exception:
        print("[supply/demand] FAILED:")
        traceback.print_exc()

    if alert_reasons:
        body_lines = [
            f"{config.EVENT_NAME} - {config.EVENT_DATE} @ {config.EVENT_VENUE}",
            "",
            "Price drop detected:",
            *[f"- {r}" for r in alert_reasons],
            "",
            f"StubHub: {config.STUBHUB_URL}",
            f"SeatGeek: https://seatgeek.com/event/{config.SEATGEEK_EVENT_ID}",
            f"Vivid Seats: {config.VIVIDSEATS_URL}",
        ]
        if signal_text:
            body_lines += ["", "Supply/demand signal:", signal_text]

        alerts.send_email(
            subject=f"Noah Kahan {config.EVENT_DATE} price drop!",
            body="\n".join(body_lines),
        )
        print("Alert email sent.")
    else:
        print("No alert-worthy price drop this run.")


if __name__ == "__main__":
    main()
