"""One polling pass over every configured target.

Shared by all three entry points (CLI, Vercel cron handler, Fly worker) so
they can't drift apart in behaviour.
"""

import logging

import config
import notify
import sniper
from resy_api import ResyClient

logger = logging.getLogger(__name__)


def build_client():
    if not config.RESY_API_KEY or not config.RESY_AUTH_TOKEN:
        raise RuntimeError(
            "RESY_API_KEY and RESY_AUTH_TOKEN must be set. Both come from the "
            "Network tab of your logged-in resy.com session - see README.md."
        )
    return ResyClient(
        api_key=config.RESY_API_KEY,
        auth_token=config.RESY_AUTH_TOKEN,
        min_request_interval=config.MIN_REQUEST_INTERVAL,
    )


def run_once(client=None, live_booking=None, targets=None, send_email=True):
    """Check every target once. Returns the list of Outcomes."""
    client = client or build_client()
    if live_booking is None:
        live_booking = config.LIVE_BOOKING
    targets = targets if targets is not None else config.TARGETS

    outcomes = []
    for target in targets:
        try:
            outcome = sniper.snipe(client, target, live_booking)
        except Exception as exc:
            # One bad target shouldn't stop the others, and an auth failure
            # on a schedule should be visible in logs rather than silent.
            logger.exception("[%s] pass failed", target.key)
            outcome = sniper.Outcome(sniper.NO_MATCH, target, reason=f"error: {exc}")

        outcomes.append(outcome)
        logger.info("[%s] %s - %s", target.key, outcome.status, outcome.reason or "")
        if send_email:
            notify.notify(outcome)

    return outcomes
