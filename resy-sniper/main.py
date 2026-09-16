import logging
import random
import time

import alerts
import config
import github_sync
import request_parser
import resy_api
import targets as targets_module

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


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


def find_target_slot(key, venue_id, criteria):
    """Check every candidate date in order; return (day, slot) for the
    first time-window-matching slot found, or (None, None) if nothing's
    open yet. A single date failing (Resy 5xx, timeout, etc. - observed
    live, not hypothetical) doesn't block checking the rest: Resy's API is
    flaky enough that one bad date shouldn't hide a real opening on a
    later one for the rest of this poll round.
    """
    for day in criteria.candidate_dates():
        try:
            slots = resy_api.find_slots(venue_id, day, criteria.party_size)
        except Exception:
            logger.exception("[%s][%s] slot check failed, skipping this date this round", key, day)
            continue
        matching = [s for s in slots if criteria.in_time_window(resy_api.slot_time(s))]
        if matching:
            return day, matching[0]
        logger.info("[%s][%s] no matching slots for party of %d yet", key, day, criteria.party_size)
    return None, None


def try_book(watch, day, slot, payment_method_id):
    criteria = watch.criteria
    config_id = slot["config"]["token"]
    book_token = resy_api.get_book_token(config_id, day, criteria.party_size)

    if watch.dry_run:
        logger.warning(
            "[%s][DRY RUN] would book %s %s party of %d (book_token=%s...) - "
            "set dry_run=false to actually book",
            watch.key, day, resy_api.slot_time(slot), criteria.party_size, book_token[:12],
        )
        return None

    result = resy_api.book(book_token, payment_method_id)
    reservation_id = result.get("resy_token") or result.get("reservation_id")

    try:
        github_sync.record_booking(watch.key, day, resy_api.slot_time(slot), reservation_id)
    except Exception:
        logger.exception(
            "[%s] booked but failed to record it in targets.json - the reservation itself "
            "is real, this only affects whether the webapp/next restart knows about it",
            watch.key,
        )

    alerts.send_email(
        subject=f"Booked! {watch.target.venue_name} - {day}",
        body=(
            f"Booked {watch.target.venue_name} ({watch.key}) for {criteria.party_size} "
            f"on {day} at {resy_api.slot_time(slot)}.\n\n"
            f"Reservation id: {reservation_id}\n\nRaw response: {result}"
        ),
    )
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

        criteria = request_parser.parse(target.request)
        if target.party_size_override:
            criteria.party_size = target.party_size_override
        logger.info("[%s] watching: %s", target.key, criteria)

        venue_id = target.venue_id or resy_api.find_venue(target.venue_name)
        watches.append(Watch(target, criteria, venue_id))
    return watches


def main():
    watches = build_watches()

    payment_method_id = None
    if watches:
        payment_method_id = config.PAYMENT_METHOD_ID or resy_api.get_default_payment_method_id()
        if payment_method_id is None:
            logger.warning(
                "no payment method on file - booking will only work for no-deposit venues"
            )

    while watches:
        still_watching = []
        for watch in watches:
            try:
                day, slot = find_target_slot(watch.key, watch.venue_id, watch.criteria)
                if slot:
                    logger.info("[%s] slot found: %s %s - attempting to book",
                                watch.key, day, resy_api.slot_time(slot))
                    if try_book(watch, day, slot, payment_method_id):
                        continue  # booked - drop from the watch list
                still_watching.append(watch)
            except Exception:
                logger.exception("[%s] poll iteration failed, will retry", watch.key)
                still_watching.append(watch)
        watches = still_watching

        if watches:
            time.sleep(config.POLL_INTERVAL_SECONDS + random.uniform(0, config.POLL_JITTER_SECONDS))

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
