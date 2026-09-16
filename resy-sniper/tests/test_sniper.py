from datetime import date, datetime, timedelta, timezone

import pytest

import sniper
from resy_api import SlotUnavailable
from tests.factories import FakeClient, make_details, make_slot, make_target

# --- date generation ---------------------------------------------------

def test_target_dates_only_returns_matching_weekdays():
    target = make_target(weekdays=(5,), days_ahead=21)
    days = sniper.target_dates(target, today=date(2026, 9, 15))  # a Tuesday

    assert days == ["2026-09-19", "2026-09-26", "2026-10-03"]
    assert all(date.fromisoformat(d).weekday() == 5 for d in days)


def test_target_dates_includes_today_when_it_matches():
    target = make_target(weekdays=(5,), days_ahead=1)
    assert sniper.target_dates(target, today=date(2026, 9, 19))[0] == "2026-09-19"


def test_target_dates_respects_days_ahead():
    target = make_target(weekdays=(0, 1, 2, 3, 4, 5, 6), days_ahead=3)
    assert len(sniper.target_dates(target, today=date(2026, 9, 15))) == 4


# --- slot ranking ------------------------------------------------------

def test_preferred_window_beats_merely_acceptable():
    target = make_target()
    ranked = sniper.rank_slots(target, [make_slot("17:15"), make_slot("19:30")])

    assert [s.time_str for s in ranked] == ["7:30 PM", "5:15 PM"]


def test_slots_outside_acceptable_window_are_dropped():
    target = make_target()
    ranked = sniper.rank_slots(target, [make_slot("12:00"), make_slot("23:00")])

    assert ranked == []


def test_bar_seating_excluded_by_default():
    target = make_target()
    ranked = sniper.rank_slots(target, [make_slot("19:00", config_type="Bar Counter")])

    assert ranked == []


def test_bar_seating_included_but_ranked_below_tables_when_allowed():
    target = make_target(allow_bar_seating=True)
    slots = [make_slot("19:30", config_type="Bar Counter"), make_slot("19:30", "Dining Room")]
    ranked = sniper.rank_slots(target, slots)

    assert [s.config_type for s in ranked] == ["Dining Room", "Bar Counter"]


def test_closest_to_middle_of_preferred_window_wins():
    # 6-9pm window -> midpoint 7:30pm; 7:45 is closer than 6:00.
    target = make_target()
    ranked = sniper.rank_slots(target, [make_slot("18:00"), make_slot("19:45"), make_slot("20:45")])

    assert ranked[0].time_str == "7:45 PM"


# --- double-booking guard ---------------------------------------------

def test_existing_reservation_detected_by_nested_venue_id():
    reservations = [{"venue": {"id": {"resy": 1234}}, "day": "2026-09-19"}]
    assert sniper.has_existing_reservation(reservations, 1234, "2026-09-19")


def test_existing_reservation_detected_by_flat_venue_id_and_timestamp():
    reservations = [{"venue_id": 1234, "date_start": "2026-09-19 19:00:00"}]
    assert sniper.has_existing_reservation(reservations, 1234, "2026-09-19")


def test_reservation_at_another_venue_or_day_does_not_match():
    reservations = [
        {"venue": {"id": {"resy": 9999}}, "day": "2026-09-19"},
        {"venue": {"id": {"resy": 1234}}, "day": "2026-09-26"},
    ]
    assert not sniper.has_existing_reservation(reservations, 1234, "2026-09-19")


def test_malformed_reservation_records_do_not_raise():
    assert not sniper.has_existing_reservation([{}, {"venue": {}}], 1234, "2026-09-19")


# --- the booking decision ---------------------------------------------

def test_dry_run_does_not_book():
    client = FakeClient()
    outcome = sniper.book_slot(client, make_target(), "2026-09-19", make_slot("19:00"), False)

    assert outcome.status == sniper.DRY_RUN
    assert client.booked == []


def test_live_booking_books_and_returns_confirmation():
    client = FakeClient()
    outcome = sniper.book_slot(client, make_target(), "2026-09-19", make_slot("19:00"), True)

    assert outcome.status == sniper.BOOKED
    assert outcome.booking.confirmation == "CONF123"
    assert client.booked == [("book-token", 99)]


def test_slot_with_cancellation_fee_above_ceiling_is_refused():
    client = FakeClient(details=make_details(fee=25.0))
    outcome = sniper.book_slot(client, make_target(), "2026-09-19", make_slot("19:00"), True)

    assert outcome.status == sniper.SKIPPED_FEE
    assert "$25.00 cancellation fee" in outcome.reason
    assert client.booked == []


def test_cancellation_fee_within_ceiling_is_accepted():
    client = FakeClient(details=make_details(fee=25.0))
    target = make_target(max_cancellation_fee=30.0)
    outcome = sniper.book_slot(client, target, "2026-09-19", make_slot("19:00"), True)

    assert outcome.status == sniper.BOOKED


def test_fee_slot_without_payment_method_is_refused():
    client = FakeClient(details=make_details(fee=10.0, payment_id=None))
    target = make_target(max_cancellation_fee=50.0)
    outcome = sniper.book_slot(client, target, "2026-09-19", make_slot("19:00"), True)

    assert outcome.status == sniper.SKIPPED_FEE
    assert "payment method" in outcome.reason


def test_expired_book_token_is_not_used():
    expired = datetime.now(timezone.utc) - timedelta(seconds=5)
    client = FakeClient(details=make_details(expires_at=expired))
    outcome = sniper.book_slot(client, make_target(), "2026-09-19", make_slot("19:00"), True)

    assert outcome.status == sniper.TAKEN
    assert client.booked == []


def test_slot_taken_between_find_and_book():
    client = FakeClient(book_error=SlotUnavailable("Slot is no longer available"))
    outcome = sniper.book_slot(client, make_target(), "2026-09-19", make_slot("19:00"), True)

    assert outcome.status == sniper.TAKEN


# --- full pass ---------------------------------------------------------

@pytest.fixture
def today():
    return date(2026, 9, 15)  # Tuesday


def test_snipe_books_the_first_matching_date(today):
    client = FakeClient(slots_by_day={"2026-09-26": [make_slot("19:30", day="2026-09-26")]})
    outcome = sniper.snipe(client, make_target(), live_booking=True, today=today)

    assert outcome.status == sniper.BOOKED
    assert outcome.day == "2026-09-26"


def test_snipe_reports_no_match_when_nothing_is_available(today):
    outcome = sniper.snipe(FakeClient(), make_target(), live_booking=True, today=today)

    assert outcome.status == sniper.NO_MATCH


def test_snipe_skips_a_day_already_reserved(today):
    client = FakeClient(
        slots_by_day={
            "2026-09-19": [make_slot("19:30", day="2026-09-19")],
            "2026-09-26": [make_slot("19:30", day="2026-09-26")],
        },
        reservations=[{"venue": {"id": {"resy": 1234}}, "day": "2026-09-19"}],
    )
    outcome = sniper.snipe(client, make_target(), live_booking=True, today=today)

    assert outcome.day == "2026-09-26"


def test_snipe_without_venue_id_fails_clearly():
    outcome = sniper.snipe(FakeClient(), make_target(venue_id=0), live_booking=True)

    assert outcome.status == sniper.NO_MATCH
    assert "find-venue" in outcome.reason


def test_snipe_falls_through_to_the_next_slot_when_one_is_taken(today):
    client = FakeClient(
        slots_by_day={"2026-09-19": [make_slot("19:30", day="2026-09-19")]},
        book_error=SlotUnavailable("gone"),
    )
    outcome = sniper.snipe(client, make_target(), live_booking=True, today=today)

    assert outcome.status == sniper.TAKEN


# --- weekday override (testing affordance) ----------------------------

def test_env_weekdays_parses_a_single_day(monkeypatch):
    import config

    monkeypatch.setenv("RESY_WEEKDAYS", "5")
    assert config._env_weekdays("RESY_WEEKDAYS", (0,)) == (5,)


def test_env_weekdays_parses_a_list(monkeypatch):
    import config

    monkeypatch.setenv("RESY_WEEKDAYS", "0,1,2,3,4,5,6")
    assert config._env_weekdays("RESY_WEEKDAYS", (5,)) == (0, 1, 2, 3, 4, 5, 6)


def test_env_weekdays_tolerates_trailing_separators(monkeypatch):
    import config

    monkeypatch.setenv("RESY_WEEKDAYS", "4,5,")
    assert config._env_weekdays("RESY_WEEKDAYS", (5,)) == (4, 5)


def test_env_weekdays_falls_back_when_unset(monkeypatch):
    import config

    monkeypatch.delenv("RESY_WEEKDAYS", raising=False)
    assert config._env_weekdays("RESY_WEEKDAYS", (5,)) == (5,)
