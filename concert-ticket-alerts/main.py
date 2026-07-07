import logging
import os

import alerts
import config
import github_issue
import health
import seatgeek_api
import storage
import supply_demand
from scrapers import seatgeek as seatgeek_scraper
from scrapers import stubhub, vividseats

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def check_source(namespace, price_per_ticket, event, confidence=None):
    """Log a price reading and return an alert reason if it's a significant drop."""
    if price_per_ticket is None:
        logger.warning("[%s] no price found this run", namespace)
        return None

    floor_before = storage.running_floor(namespace)
    storage.append_record(namespace, {"price_per_ticket": price_per_ticket})
    logger.info(
        "[%s] $%.0f/ticket (previous floor: %s)", namespace, price_per_ticket, floor_before
    )
    return alerts.check_price_drop(
        namespace, price_per_ticket, floor_before,
        event.price_target_per_ticket, event.pct_drop_threshold,
        confidence=confidence,
    )


def check_scraped_source(namespace, scraper, url, event):
    """Returns (status, price_per_ticket, alert_reason_or_None)."""
    result = scraper.check_price(url)
    consecutive, just_recovered = health.record_outcome(namespace, result["status"])
    logger.info(
        "[%s] status=%s confidence=%s price=%s",
        namespace, result["status"], result.get("confidence"), result.get("price_per_ticket"),
    )
    if result["status"] == "fallback" and result.get("diagnostic"):
        # fallback alone doesn't escalate to a GitHub issue, but this is
        # exactly the breadcrumb needed to stop guessing blind at why
        # structured extraction found nothing - surface it in the logs.
        logger.info("[%s] fallback diagnostic: %s", namespace, result["diagnostic"])

    if result["status"] in ("blocked", "error"):
        if consecutive >= config.ESCALATION_THRESHOLD:
            try:
                github_issue.escalate(namespace, result.get("diagnostic", ""))
                logger.warning(
                    "[%s] escalated to GitHub issue (failed %dx in a row)", namespace, consecutive
                )
            except Exception:
                logger.exception("[%s] failed to escalate to GitHub", namespace)
        return result["status"], None, None

    if just_recovered:
        try:
            github_issue.resolve(namespace)
            logger.info("[%s] recovered - resolved GitHub issue", namespace)
        except Exception:
            logger.exception("[%s] failed to resolve GitHub issue", namespace)

    price = result.get("price_per_ticket")
    reason = check_source(namespace, price, event, confidence=result.get("confidence"))
    return result["status"], price, reason


def write_step_summary(event, source_results, alert_reasons, signal_text):
    """Append a markdown table to the GitHub Actions run summary, if running
    in Actions (GITHUB_STEP_SUMMARY is only set there). Makes a run's
    outcome visible at a glance without opening raw logs.
    """
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    lines = [
        f"### {event.name} ({event.date})",
        "",
        "| Source | Status | Price/ticket |",
        "| --- | --- | --- |",
    ]
    for source, status, price in source_results:
        price_str = f"${price:.0f}" if price is not None else "-"
        lines.append(f"| {source} | {status} | {price_str} |")

    if alert_reasons:
        lines += ["", "**Alert email sent:**"] + [f"- {r}" for r in alert_reasons]
    else:
        lines += ["", "_No alert-worthy price drop this run._"]

    if signal_text:
        lines += ["", f"_{signal_text}_"]

    lines.append("")
    with open(summary_path, "a") as f:
        f.write("\n".join(lines) + "\n")


def check_seatgeek(event, source_results, alert_reasons):
    """SeatGeek's official API is the reliable primary source. If it isn't
    configured (no SEATGEEK_CLIENT_ID) or the call itself fails, fall back
    to scraping seatgeek.com directly - same tiered scraper as StubHub/
    Vivid Seats, sharing storage/health namespace with the API path so
    price history and escalation stay continuous regardless of source.
    """
    namespace = f"{event.key}__seatgeek"

    if seatgeek_api.is_configured():
        try:
            stats = seatgeek_api.get_event_stats(event.seatgeek_event_id)
            reason = check_source(namespace, stats["lowest_price"], event)
            source_results.append(("seatgeek (api)", "ok", stats["lowest_price"]))
            if reason:
                alert_reasons.append(reason)
            return
        except Exception:
            logger.exception("[%s] API call failed, falling back to scraping", namespace)
    else:
        logger.warning("[%s] SEATGEEK_CLIENT_ID not set, falling back to scraping", namespace)

    try:
        status, price, reason = check_scraped_source(
            namespace, seatgeek_scraper, event.seatgeek_url, event
        )
        source_results.append(("seatgeek (scraped)", status, price))
        if reason:
            alert_reasons.append(reason)
    except Exception:
        logger.exception("[%s] scraping fallback FAILED", namespace)
        source_results.append(("seatgeek (scraped)", "error", None))


def process_event(event):
    alert_reasons = []
    source_results = []  # (source_name, status, price_per_ticket)

    check_seatgeek(event, source_results, alert_reasons)

    # StubHub / Vivid Seats: best-effort scraping, may fail - don't let a
    # failure here block the other sources.
    for site_name, scraper, url in [
        ("stubhub", stubhub, event.stubhub_url),
        ("vividseats", vividseats, event.vividseats_url),
    ]:
        namespace = f"{event.key}__{site_name}"
        try:
            status, price, reason = check_scraped_source(namespace, scraper, url, event)
            source_results.append((site_name, status, price))
            if reason:
                alert_reasons.append(reason)
        except Exception:
            logger.exception("[%s] FAILED", namespace)
            source_results.append((site_name, "error", None))

    # Supply/demand signal across the whole tour (also needs SeatGeek).
    signal_text = None
    if not seatgeek_api.is_configured():
        logger.warning(
            "[%s__supply_demand] skipped - SEATGEEK_CLIENT_ID is not set", event.key
        )
    else:
        try:
            snapshots = supply_demand.snapshot_tour(event.key, event.seatgeek_performer_slug)
            signal_text = supply_demand.build_signal(event.key, snapshots, event.seatgeek_event_id)
            if signal_text:
                logger.info("[%s__supply_demand] %s", event.key, signal_text)
        except Exception:
            logger.exception("[%s__supply_demand] FAILED", event.key)

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
        logger.info("[%s] Alert email sent.", event.key)
    else:
        logger.info("[%s] No alert-worthy price drop this run.", event.key)

    write_step_summary(event, source_results, alert_reasons, signal_text)


def main():
    for event in config.WATCHED_EVENTS:
        process_event(event)


if __name__ == "__main__":
    main()
