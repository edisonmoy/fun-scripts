"""Small builders so tests read as intent rather than boilerplate."""

from datetime import datetime, time

from config import Target
from resy_api import BookingDetails, Slot


def make_target(**overrides):
    defaults = dict(
        key="test-venue",
        name="Test Venue",
        venue_id=1234,
        party_size=2,
        weekdays=(5,),
        days_ahead=30,
        preferred_start=time(18, 0),
        preferred_end=time(21, 0),
        acceptable_start=time(17, 0),
        acceptable_end=time(22, 0),
        allow_bar_seating=False,
        max_cancellation_fee=0.0,
    )
    defaults.update(overrides)
    return Target(**defaults)


def make_slot(hhmm, config_type="Dining Room", day="2026-09-19"):
    start = datetime.strptime(f"{day} {hhmm}", "%Y-%m-%d %H:%M")
    return Slot(
        start=start,
        end=start,
        config_id=1,
        config_type=config_type,
        token=f"rgs://resy/1234/1/2/{day}/{day}/{hhmm}:00/2/{config_type}",
    )


def make_details(fee=0.0, payment_id=99, expires_at=None):
    return BookingDetails(
        book_token="book-token",
        expires_at=expires_at,
        payment_method_ids=[payment_id] if payment_id else [],
        default_payment_method_id=payment_id,
        cancellation_fee=fee,
        cancellation_text="Cancel 24h ahead" if fee else "",
    )


class FakeClient:
    """Stand-in for ResyClient. Records what was booked."""

    def __init__(self, slots_by_day=None, details=None, reservations=None, book_error=None):
        self.slots_by_day = slots_by_day or {}
        self._details = details or make_details()
        self._reservations = reservations or []
        self.book_error = book_error
        self.booked = []
        self.find_calls = []

    def find_slots(self, venue_id, day, party_size):
        self.find_calls.append(day)
        return self.slots_by_day.get(day, [])

    def get_booking_details(self, config_token, day, party_size):
        return self._details

    def book(self, book_token, payment_method_id=None):
        if self.book_error:
            raise self.book_error
        from resy_api import Booking

        self.booked.append((book_token, payment_method_id))
        return Booking(resy_token="resy-token", confirmation="CONF123")

    def reservations(self, limit=20):
        return self._reservations
