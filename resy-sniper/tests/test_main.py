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


def _target(**overrides):
    from targets import Target

    defaults = dict(key="test-target", venue_name="Test Venue", request="test request")
    defaults.update(overrides)
    return Target(**defaults)


def test_try_book_in_notify_mode_emails_and_stops_watching_without_booking():
    target = _target(dry_run=True)
    watch = main.Watch(target, _criteria(), venue_id=12345)
    slot = {"config": {"token": "config-token"}, "date": {"start": "2026-09-19 19:00:00"}}

    with patch("main.resy_api.get_book_token", return_value="book-token") as mock_get_token, \
         patch("main.resy_api.book") as mock_book, \
         patch("main.github_sync.record_booking") as mock_record, \
         patch("main.alerts.send_email") as mock_email:
        result = main.try_book(watch, "2026-09-19", slot, payment_method_id=None)

    assert result is True
    mock_get_token.assert_called_once()
    mock_book.assert_not_called()
    mock_record.assert_not_called()
    mock_email.assert_called_once()
    assert "notify mode" in mock_email.call_args.kwargs["subject"].lower()


def test_try_book_in_book_mode_books_and_records():
    target = _target(dry_run=False)
    watch = main.Watch(target, _criteria(), venue_id=12345)
    slot = {"config": {"token": "config-token"}, "date": {"start": "2026-09-19 19:00:00"}}
    fake_result = {"reservation_id": 999}

    with patch("main.resy_api.get_book_token", return_value="book-token"), \
         patch("main.resy_api.book", return_value=fake_result) as mock_book, \
         patch("main.github_sync.record_booking") as mock_record, \
         patch("main.alerts.send_email") as mock_email:
        result = main.try_book(watch, "2026-09-19", slot, payment_method_id=42)

    assert result == 999
    mock_book.assert_called_once_with("book-token", 42)
    mock_record.assert_called_once_with("test-target", "2026-09-19", "19:00", 2, 999)
    mock_email.assert_called_once()
    assert "notify mode" not in mock_email.call_args.kwargs["subject"].lower()
