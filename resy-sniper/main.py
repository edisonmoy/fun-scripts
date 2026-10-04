import logging
import random
import time

import alerts
import config
import github_sync
import request_parser
import resy_api
import targets as targets_module

# How often to re-read the account's upcoming reservations from Resy, so
# ones booked by hand mid-run are respected. Always re-checked right
# before a booking too.
RESY_RESERVATIONS_REFRESH_SECONDS = 300

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class ReservedDays:
    """Days that already have a reservation, so the bot doesn't book a
    second one: bookings recorded in targets.json, the account's upcoming
    reservations on Resy (including ones made by hand), and bookings made
    this run. Supports `day in reserved`.
    """

    def __init__(self, known=()):
        self._known = set(known)
        self._on_resy = set()
        self._fetched_at = None

    def refresh(self, max_age=RESY_RESERVATIONS_REFRESH_SECONDS):
        now = time.monotonic()
        if self._fetched_at is not None and now - self._fetched_at < max_age:
            return
        try:
            days = resy_api.upcoming_reservation_days()
        except Exception:
            # Keep the last known list and retry next round, rather than
            # stopping every target over a flaky read-only call.
            logger.exception("couldn't fetch upcoming reservations from Resy - using last known")
            return
        if days != self._on_resy:
            logger.info("upcoming reservations on Resy: %s", sorted(days))
        self._on_resy = days
        self._fetched_at = now

    def add(self, day):
        self._known.add(day)

    def __contains__(self, day):
        return day in self._known or day in self._on_resy


class Watch:
    """A target plus everything resolved for it at startup (parsed
    criteria, venue id). Kept separate from the Target dataclass - which
    mirrors targets.json 1:1 - so parsing/resolution happens once per
    process, not on every poll round.
    """

    def __init__(self, target, criteria, venue_id):
        self.target = target
        self.criteria = criteria
        self.venue_id = venue_id

    @property
    def key(self):
        return self.target.key

    @property
    def dry_run(self):
        return config.DRY_RUN if self.target.dry_run is None else self.target.dry_run

    @property
    def allow_same_day(self):
        return self.criteria.allow_same_day


def find_target_slot(key, venue_id, criteria, booked_days=frozenset()):
    """Check every candidate date in order; return (day, slot, all_failed).
    Dates in booked_days are skipped - never two reservations on one day,
    whichever targets (or hand-made Resy bookings) they come from, unless
    the target's request opts out (allow_same_day).
    day/slot are the first time-window-matching slot found, or None if
    nothing's open yet. all_failed is True when every single date errored
    (vs. legitimately having no availability) - the caller uses this to
    back off, since a run of these usually means Resy itself is having
    trouble (observed live) rather than random bad luck on one date. A
    single date failing doesn't block checking the rest: one bad date
    shouldn't hide a real opening on a later one in the same round.
    """
    dates = [d for d in criteria.candidate_dates() if d not in booked_days]
    errors = 0
    for day in dates:
        try:
            slots = resy_api.find_slots(venue_id, day, criteria.party_size)
        except Exception:
            logger.exception("[%s][%s] slot check failed, skipping this date this round", key, day)
            errors += 1
            continue
        matching = [s for s in slots if criteria.in_time_window(resy_api.slot_time(s))]
        if matching:
            return day, matching[0], False
        logger.info("[%s][%s] no matching slots for party of %d yet", key, day, criteria.party_size)
    return None, None, bool(dates) and errors == len(dates)


def try_book(watch, day, slot, payment_method_id):
    criteria = watch.criteria
    config_id = slot["config"]["token"]
    book_token = resy_api.get_book_token(config_id, day, criteria.party_size)

    if watch.dry_run:
        logger.info(
            "[%s] NOTIFY MODE: match found %s %s party of %d - sending alert, not booking",
            watch.key, day, resy_api.slot_time(slot), criteria.party_size,
        )
        alerts.send_email(
            subject=f"Match found (notify mode): {watch.target.venue_name} - {day}",
            body=(
                f"{watch.target.venue_name} ({watch.key}) has an opening for "
                f"{criteria.party_size} on {day} at {resy_api.slot_time(slot)}.\n\n"
                "This target is in notify mode, so nothing was booked - switch it to book "
                "mode in the dashboard if you want the bot to grab slots like this "
                "automatically.\n\nThis target stops watching now that it's found a match, "
                "for the rest of this run - it resumes watching from scratch on the next "
                "restart/redeploy."
            ),
        )
        # Stop watching (like a real booking would) so the same open slot
        # doesn't re-trigger an identical email every poll round. Nothing is
        # persisted, so a redeploy resumes watching fresh - deliberate,
        # since a notify-mode match isn't a terminal outcome the way a
        # booking is.
        return True

    result = resy_api.book(book_token, payment_method_id)
    # reservation_id (a stable small int) is what /3/cancel needs to look up
    # later - resy_token also appears here but rotates on every fetch of
    # /3/user/reservations, so it's useless to persist (confirmed live:
    # the token captured at book time no longer matched the one the
    # reservations list returned minutes later).
    reservation_id = result.get("reservation_id") or result.get("resy_token")

    try:
        github_sync.record_booking(
            watch.key, day, resy_api.slot_time(slot), criteria.party_size, reservation_id
        )
    except Exception:
        logger.exception(
            "[%s] booked but failed to record it in targets.json - the reservation itself "
            "is real, this only affects whether the webapp/next restart knows about it",
            watch.key,
        )

    # The reservation is real at this point - a failed email must not
    # propagate, or the poll loop keeps watching and books a second time.
    try:
        alerts.send_email(
            subject=f"Booked! {watch.target.venue_name} - {day}",
            body=(
                f"Booked {watch.target.venue_name} ({watch.key}) for {criteria.party_size} "
                f"on {day} at {resy_api.slot_time(slot)}.\n\n"
                f"Reservation id: {reservation_id}\n\nRaw response: {result}"
            ),
        )
    except Exception:
        logger.exception("[%s] booked but the confirmation email failed", watch.key)
    logger.info(
        "[%s] BOOKED %s %s - confirmation email sent", watch.key, day, resy_api.slot_time(slot)
    )
    return reservation_id


def build_watches():
    watches = []
    for target in targets_module.load():
        if not target.enabled:
            logger.info("[%s] disabled, skipping", target.key)
            continue
        if target.booking:
            logger.info("[%s] already booked: %s - skipping", target.key, target.booking)
            continue

        # One unparseable request must not take down every other target's
        # watch - skip it (the log says why) and keep going.
        try:
            criteria = request_parser.parse(target.request)
        except Exception:
            logger.exception("[%s] could not parse request - skipping this target", target.key)
            continue
        logger.info("[%s] watching: %s", target.key, criteria)

        venue_id = target.venue_id or resy_api.find_venue(target.venue_name)
        watches.append(Watch(target, criteria, venue_id))
    return watches


def booked_days_from_targets():
    """Days that already have a reservation from any target, booked in an
    earlier run (github_sync records them in targets.json)."""
    return {t.booking["day"] for t in targets_module.load() if t.booking}


def main():
    watches = build_watches()
    reserved = ReservedDays(booked_days_from_targets())

    payment_method_id = None
    if watches:
        payment_method_id = config.PAYMENT_METHOD_ID or resy_api.get_default_payment_method_id()
        if payment_method_id is None:
            logger.warning(
                "no payment method on file - booking will only work for no-deposit venues"
            )

    consecutive_bad_rounds = 0
    while watches:
        still_watching = []
        any_target_all_failed = False
        reserved.refresh()
        for watch in watches:
            try:
                skip_days = frozenset() if watch.allow_same_day else reserved
                day, slot, all_failed = find_target_slot(
                    watch.key, watch.venue_id, watch.criteria, skip_days
                )
                any_target_all_failed = any_target_all_failed or all_failed
                if slot and not watch.dry_run and not watch.allow_same_day:
                    reserved.refresh(max_age=0)  # catch a reservation made by hand just now
                    if day in reserved:
                        logger.info("[%s] %s now has another reservation - not booking it",
                                    watch.key, day)
                        still_watching.append(watch)
                        continue
                if slot:
                    logger.info("[%s] slot found: %s %s - attempting to book",
                                watch.key, day, resy_api.slot_time(slot))
                    if try_book(watch, day, slot, payment_method_id):
                        if not watch.dry_run:
                            reserved.add(day)  # later targets this round skip it too
                        continue  # booked - drop from the watch list
                still_watching.append(watch)
            except Exception:
                logger.exception("[%s] poll iteration failed, will retry", watch.key)
                still_watching.append(watch)
        watches = still_watching

        # Every date erroring for a target usually means Resy itself is
        # struggling (observed live: sustained several-minute stretches of
        # every request failing, isolated from anything specific to our
        # code or credentials), not random bad luck on one date. Back off
        # exponentially while that persists instead of hammering it every
        # ~2s, capped at 30x and reset the instant a round comes back
        # clean - this shouldn't slow down catching a real opening once
        # Resy recovers.
        consecutive_bad_rounds = consecutive_bad_rounds + 1 if any_target_all_failed else 0
        backoff = min(2**consecutive_bad_rounds, 30)
        if backoff > 1:
            logger.warning(
                "every date errored for at least one target this round (%dx in a row) - "
                "backing off %dx this round",
                consecutive_bad_rounds, backoff,
            )

        if watches:
            jitter = random.uniform(0, config.POLL_JITTER_SECONDS)
            time.sleep(backoff * (config.POLL_INTERVAL_SECONDS + jitter))

    # Nothing left to poll - either everything active this run got booked,
    # or there was nothing to watch to begin with (all booked/disabled, or
    # targets.json is empty). Idle instead of exiting so Fly's
    # `restart = always` doesn't spin the machine into a restart-loop -
    # exiting cleanly here previously caused exactly that.
    logger.info("nothing to watch - idling")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
