from unittest.mock import patch

import main
from request_parser import BookingCriteria


def _criteria(**overrides):
    defaults = dict(
        party_size=2,
        days_of_week=["Saturday"],
        time_window_start="17:00",
        time_window_end="21:00",
        lookahead_weeks=2,
        notes="",
    )
    defaults.update(overrides)
    return BookingCriteria(**defaults)


def test_find_target_slot_skips_a_failing_date_and_checks_the_rest():
    """Regression test: a transient Resy 5xx on one date used to abort the
    whole scan, hiding a real opening on a later date in the same round.
    """
    criteria = _criteria()
    dates = criteria.candidate_dates()
    assert len(dates) == 2

    def fake_find_slots(venue_id, day, party_size):
        if day == dates[0]:
            raise RuntimeError("simulated Resy 500")
        return [{"date": {"start": f"{day} 19:00:00"}}]

    with patch("main.resy_api.find_slots", side_effect=fake_find_slots):
        found_day, slot = main.find_target_slot("test-target", 12345, criteria)

    assert found_day == dates[1]
    assert main.resy_api.slot_time(slot) == "19:00"


def test_find_target_slot_returns_none_when_nothing_open():
    criteria = _criteria()

    with patch("main.resy_api.find_slots", return_value=[]):
        found_day, slot = main.find_target_slot("test-target", 12345, criteria)

    assert found_day is None
    assert slot is None


def test_find_target_slot_filters_by_time_window():
    criteria = _criteria(time_window_start="17:00", time_window_end="21:00")

    def fake_find_slots(venue_id, day, party_size):
        return [{"date": {"start": f"{day} 11:00:00"}}]  # outside the window

    with patch("main.resy_api.find_slots", side_effect=fake_find_slots):
        found_day, slot = main.find_target_slot("test-target", 12345, criteria)

    assert found_day is None
    assert slot is None
