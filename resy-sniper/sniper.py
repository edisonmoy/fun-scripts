"""Slot selection and the booking decision, kept separate from I/O so the
interesting logic is unit-testable without touching Resy."""

import logging
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime, timedelta

from resy_api import SlotUnavailable

logger = logging.getLogger(__name__)

# Outcome statuses (also used in the notification email subject).
BOOKED = "booked"
DRY_RUN = "dry_run"
NO_MATCH = "no_match"
ALREADY_BOOKED = "already_booked"
SKIPPED_FEE = "skipped_fee"
TAKEN = "taken"


@dataclass
class Outcome:
    status: str
    target: object
    day: str | None = None
    slot: object = None
    details: object = None
    booking: object = None
    reason: str = ""

    @property
    def is_success(self):
        return self.status == BOOKED


def target_dates(target, today=None):
    """Every upcoming date matching the target's weekdays, soonest first.

    Soonest-first matters: a table three weeks out is worth more than the
    same table two months out, and it keeps the request count bounded when
    we stop at the first success.
    """
    today = today or date_cls.today()
    return [
        (today + timedelta(days=offset)).isoformat()
        for offset in range(target.days_ahead + 1)
        if (today + timedelta(days=offset)).weekday() in target.weekdays
    ]


def _minutes(t):
    return t.hour * 60 + t.minute


def _in_window(slot, start, end):
    return _minutes(start) <= _minutes(slot.start.time()) <= _minutes(end)


def rank_slots(target, slots):
    """Acceptable slots, best first. Unacceptable slots are dropped entirely.

    Ordering, in priority order:
      1. inside the preferred (dinner) window beats merely acceptable
      2. a real table beats a bar/counter stool
      3. closest to the middle of the preferred window - for a 6-9pm
         window that lands on ~7:30pm, which is the slot most people
         actually want, rather than a technically-valid 5:00pm
      4. earliest, as a stable tiebreak
    """
    midpoint = (_minutes(target.preferred_start) + _minutes(target.preferred_end)) / 2
    ranked = []
    for slot in slots:
        is_bar = target.slot_is_bar(slot.config_type)
        if is_bar and not target.allow_bar_seating:
            continue

        if _in_window(slot, target.preferred_start, target.preferred_end):
            tier = 0
        elif _in_window(slot, target.acceptable_start, target.acceptable_end):
            tier = 1
        else:
            continue

        ranked.append(
            (tier, is_bar, abs(_minutes(slot.start.time()) - midpoint), slot.start, slot)
        )

    ranked.sort(key=lambda row: row[:4])
    return [row[4] for row in ranked]


def has_existing_reservation(reservations, venue_id, day):
    """True if the account already holds a reservation at this venue on this day.

    This is the guard that makes a stateless deployment (Vercel Cron, where
    every invocation starts cold) safe to run: without it, two overlapping
    invocations could each book the same night.

    The /3/user/reservations payload shape isn't documented and wasn't
    verifiable when this was written, so the lookup is deliberately
    tolerant - it digs for a venue id and a date anywhere in the record
    rather than assuming one exact key path.
    """
    for res in reservations:
        venue = res.get("venue") or {}
        raw_id = venue.get("id")
        if isinstance(raw_id, dict):
            raw_id = raw_id.get("resy")
        candidates = {raw_id, venue.get("venue_id"), res.get("venue_id")}
        if venue_id not in {c for c in candidates if c is not None}:
            continue

        stamp = str(res.get("day") or res.get("date") or res.get("date_start") or "")
        if stamp.startswith(day):
            return True
    return False


def book_slot(client, target, day, slot, live_booking, fee_ceiling=None):
    """Take one ranked slot from config token -> confirmed reservation.

    `fee_ceiling` is the most this call may commit the user to, in dollars.
    It defaults to the target's configured ceiling, which is what every
    unattended path (cron, worker, snipe pass) uses. An interactive caller
    passes the exact fee the user just agreed to, after seeing the price and
    the cancellation terms - their answer is the decision, so the standing
    ceiling no longer applies to that one booking.

    Returns an Outcome. Raises nothing for the ordinary "someone beat us to
    it" case - that comes back as TAKEN so the caller can try the next slot.
    """
    if fee_ceiling is None:
        fee_ceiling = target.max_cancellation_fee

    try:
        details = client.get_booking_details(slot.token, day, target.party_size)
    except SlotUnavailable as exc:
        return Outcome(TAKEN, target, day, slot, reason=str(exc))

    # A free slot is never worth interrupting anyone over; a slot that puts
    # money on the card is never taken without a decision. That split is the
    # whole policy, and this is where it's enforced.
    if details.cancellation_fee > fee_ceiling:
        return Outcome(
            SKIPPED_FEE,
            target,
            day,
            slot,
            details,
            reason=(
                f"slot carries a ${details.cancellation_fee:.2f} cancellation fee, "
                f"above the ${fee_ceiling:.2f} ceiling "
                f"(RESY_MAX_CANCELLATION_FEE). Policy: "
                f"{details.cancellation_text or 'not stated'}"
            ),
        )

    payment_method_id = details.default_payment_method_id
    if details.cancellation_fee > 0 and payment_method_id is None:
        return Outcome(
            SKIPPED_FEE,
            target,
            day,
            slot,
            details,
            reason="slot requires a payment method but the Resy account has none on file",
        )

    if not live_booking:
        return Outcome(
            DRY_RUN,
            target,
            day,
            slot,
            details,
            reason="RESY_LIVE_BOOKING is not set - would have booked this slot",
        )

    if details.expires_at and details.expires_at <= datetime.now(details.expires_at.tzinfo):
        return Outcome(TAKEN, target, day, slot, details, reason="book token expired before use")

    try:
        booking = client.book(details.book_token, payment_method_id)
    except SlotUnavailable as exc:
        return Outcome(TAKEN, target, day, slot, details, reason=str(exc))

    return Outcome(BOOKED, target, day, slot, details, booking)


def snipe(client, target, live_booking, today=None, max_slot_attempts=3):
    """One full pass over a target: scan its dates, book the best slot found.

    Stops at the first booking. Days with no acceptable slot are skipped
    silently - on most passes that's every day, and that's the normal
    steady state, not an error.
    """
    if not target.venue_id:
        return Outcome(NO_MATCH, target, reason="venue_id is not set - run `find-venue` first")

    for day in target_dates(target, today):
        slots = client.find_slots(target.venue_id, day, target.party_size)
        if not slots:
            continue

        ranked = rank_slots(target, slots)
        if not ranked:
            logger.debug("[%s] %s: %d slots, none acceptable", target.key, day, len(slots))
            continue

        logger.info(
            "[%s] %s: %d acceptable slot(s), best = %s (%s)",
            target.key, day, len(ranked), ranked[0].time_str, ranked[0].config_type,
        )

        # Only consult Resy about existing reservations once we actually
        # have something bookable - it's a wasted request otherwise.
        try:
            if has_existing_reservation(client.reservations(), target.venue_id, day):
                logger.info("[%s] %s: already have a reservation, skipping", target.key, day)
                continue
        except Exception:
            # Don't let a failed guard block a live snipe; the whole point
            # is to act fast when a slot appears.
            logger.warning("[%s] could not check existing reservations", target.key, exc_info=True)

        last = None
        for slot in ranked[:max_slot_attempts]:
            last = book_slot(client, target, day, slot, live_booking)
            if last.status in (BOOKED, DRY_RUN, SKIPPED_FEE):
                return last
            logger.info("[%s] %s %s: %s", target.key, day, slot.time_str, last.reason)
        if last is not None:
            return last

    return Outcome(NO_MATCH, target, reason="no acceptable availability on any target date")
