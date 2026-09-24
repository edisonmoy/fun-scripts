import logging
import random
import time

import alerts
import availability
import checkout
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def describe(showtime):
    return (
        f"{showtime['date']} {showtime['time']} at {showtime['venue']} "
        f"(status={showtime['status']})"
    )


def handle_opening(showtime):
    """An opening was detected. Always alert first - that's the reliable
    part - then attempt auto-purchase if not in dry-run mode. Returns True
    if a purchase was completed (caller stops polling), else False.
    """
    logger.warning("OPENING DETECTED: %s", describe(showtime))
    alerts.send_email(
        subject="Cameron Winter at Carnegie - tickets may be open!",
        body=(
            f"The Oct 1 NYFF screening no longer shows sold-out/standby: {describe(showtime)}.\n\n"
            f"Buy now: {showtime['tickets_url']}\n\n"
            + (
                "Dry-run mode is on - this bot will NOT attempt to buy automatically. "
                "Go buy it by hand right now."
                if config.DRY_RUN
                else "Attempting automated purchase now - a follow-up email will say whether "
                "it worked. Given the site's bot defenses this may fail; if it does, buy it "
                "by hand immediately using the link above."
            )
        ),
    )

    if config.DRY_RUN:
        return False

    success, message = checkout.attempt_purchase(config.TICKET_QUANTITY)
    if success:
        logger.warning("PURCHASE SUCCEEDED: %s", message)
        alerts.send_email(
            subject="Cameron Winter at Carnegie - BOUGHT",
            body=f"Automated purchase reported success: {message}\n\nVerify via confirmation.",
        )
        return True

    logger.error("automated purchase failed: %s", message)
    alerts.send_email(
        subject="Cameron Winter at Carnegie - auto-purchase FAILED, buy it yourself now",
        body=(
            f"Automated purchase did not complete: {message}\n\n"
            f"Buy now by hand: {showtime['tickets_url']}"
        ),
    )
    return False


def main():
    logger.info(
        "watching performance %s (%s) for an opening, poll every ~%ds, dry_run=%s",
        config.PERFORMANCE_ID, config.FILM_PAGE_URL, config.POLL_INTERVAL_SECONDS, config.DRY_RUN,
    )

    already_alerted = False
    consecutive_errors = 0
    booked = False

    while not booked:
        try:
            showtime = availability.fetch_availability()
            consecutive_errors = 0

            if showtime["available"]:
                if not already_alerted:
                    booked = handle_opening(showtime)
                    already_alerted = True
                else:
                    logger.info("still open, already alerted: %s", describe(showtime))
            else:
                if already_alerted:
                    logger.info("opening closed again: %s", describe(showtime))
                already_alerted = False
                logger.info("still sold out: %s", describe(showtime))
        except availability.AvailabilityError as exc:
            consecutive_errors += 1
            logger.warning("availability check failed (%dx in a row): %s", consecutive_errors, exc)

        if booked:
            break

        # Back off while checks keep failing (likely bot-detection or a
        # transient site issue), same pattern as resy-sniper's find_target_slot
        # backoff - capped so a sustained bad stretch doesn't turn into
        # sustained hammering, reset the instant a check succeeds.
        backoff = min(2**consecutive_errors, 15) if consecutive_errors else 1
        jitter = random.uniform(0, config.POLL_JITTER_SECONDS)
        time.sleep(backoff * (config.POLL_INTERVAL_SECONDS + jitter))

    logger.info("done - idling")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
