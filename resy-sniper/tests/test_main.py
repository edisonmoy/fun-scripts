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
        specific_dates=[],
        allow_same_day=False,
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
        found_day, slot, all_failed = main.find_target_slot("test-target", 12345, criteria)

    assert found_day == dates[1]
    assert main.resy_api.slot_time(slot) == "19:00"
    assert all_failed is False  # one date errored, but the other succeeded


def test_find_target_slot_returns_none_when_nothing_open():
    criteria = _criteria()

    with patch("main.resy_api.find_slots", return_value=[]):
        found_day, slot, all_failed = main.find_target_slot("test-target", 12345, criteria)

    assert found_day is None
    assert slot is None
    assert all_failed is False


def test_find_target_slot_filters_by_time_window():
    criteria = _criteria(time_window_start="17:00", time_window_end="21:00")

    def fake_find_slots(venue_id, day, party_size):
        return [{"date": {"start": f"{day} 11:00:00"}}]  # outside the window

    with patch("main.resy_api.find_slots", side_effect=fake_find_slots):
        found_day, slot, all_failed = main.find_target_slot("test-target", 12345, criteria)

    assert found_day is None
    assert slot is None
    assert all_failed is False


def test_find_target_slot_reports_all_failed_when_every_date_errors():
    criteria = _criteria()

    with patch("main.resy_api.find_slots", side_effect=RuntimeError("simulated Resy 500")):
        found_day, slot, all_failed = main.find_target_slot("test-target", 12345, criteria)

    assert found_day is None
    assert slot is None
    assert all_failed is True


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


def test_build_watches_skips_a_target_whose_request_fails_to_parse():
    good = _target(key="good", request="good request", venue_id=1)
    bad = _target(key="bad", request="bad request", venue_id=2)

    def fake_parse(request):
        if request == "bad request":
            raise ValueError("time_window_start must not be after time_window_end")
        return _criteria()

    with patch("main.targets_module.load", return_value=[bad, good]), \
         patch("main.request_parser.parse", side_effect=fake_parse):
        watches = main.build_watches()

    assert [w.target.key for w in watches] == ["good"]


def test_find_target_slot_skips_days_that_already_have_a_booking():
    criteria = _criteria()  # two Saturdays
    first, second = criteria.candidate_dates()
    checked = []

    def fake_find_slots(venue_id, day, party_size):
        checked.append(day)
        return [{"date": {"start": f"{day} 19:00:00"}}]

    with patch("main.resy_api.find_slots", side_effect=fake_find_slots):
        found_day, slot, _ = main.find_target_slot("lei", 1, criteria, booked_days={first})

    assert found_day == second
    assert checked == [second]


def test_try_book_returns_the_booking_even_if_the_email_fails():
    """A failed email used to escape try_book, leaving the target watched -
    and free to book a second reservation on the next round."""
    watch = main.Watch(_target(dry_run=False), _criteria(), venue_id=12345)
    slot = {"config": {"token": "config-token"}, "date": {"start": "2026-09-19 19:00:00"}}

    with patch("main.resy_api.get_book_token", return_value="book-token"), \
         patch("main.resy_api.book", return_value={"reservation_id": 999}), \
         patch("main.github_sync.record_booking"), \
         patch("main.alerts.send_email", side_effect=RuntimeError("SMTP down")):
        assert main.try_book(watch, "2026-09-19", slot, payment_method_id=42) == 999


DATES = ["2026-10-22", "2026-10-23", "2026-10-24"]


def _run_main(watches, resy_days=(), known=()):
    """Runs main() with every target finding every date open; returns the
    (key, day) bookings made. resy_days may be a list of sets, one per
    upcoming_reservation_days() call."""
    booked = []
    if isinstance(resy_days, list):
        resy_calls = iter(resy_days)
        last = [set()]

        def fake_resy_days():
            last[0] = next(resy_calls, last[0])
            return last[0]
    else:
        def fake_resy_days():
            return set(resy_days)

    def fake_find_target_slot(key, venue_id, criteria, booked_days):
        day = next(d for d in DATES if d not in booked_days)
        return day, {"date": {"start": f"{day} 19:00:00"}}, False

    def fake_try_book(watch, day, slot, payment_method_id):
        booked.append((watch.key, day))
        return 1

    with patch("main.build_watches", return_value=watches), \
         patch("main.booked_days_from_targets", return_value=set(known)), \
         patch("main.resy_api.upcoming_reservation_days", side_effect=fake_resy_days), \
         patch("main.find_target_slot", side_effect=fake_find_target_slot), \
         patch("main.try_book", side_effect=fake_try_book), \
         patch("main.resy_api.get_default_payment_method_id", return_value=42), \
         patch("main.time.sleep", side_effect=StopIteration):
        try:
            main.main()
        except StopIteration:
            pass  # reached the idle loop
    return booked


def _watch(key, allow_same_day=False, dry_run=False):
    target = _target(key=key, venue_id=1, dry_run=dry_run)
    return main.Watch(target, _criteria(specific_dates=DATES, allow_same_day=allow_same_day), 1)


def test_main_never_books_two_targets_on_the_same_day():
    booked = _run_main([_watch("ugly-baby"), _watch("lei")])
    assert booked == [("ugly-baby", "2026-10-22"), ("lei", "2026-10-23")]


def test_main_skips_days_with_a_reservation_made_by_hand_on_resy():
    booked = _run_main([_watch("ugly-baby")], resy_days={"2026-10-22"})
    assert booked == [("ugly-baby", "2026-10-23")]


def test_main_rechecks_resy_right_before_booking():
    # Nothing on Resy at the start of the round; a reservation for Oct 22
    # appears by the time the slot is found - so the bot holds off.
    booked = _run_main([_watch("ugly-baby")], resy_days=[set(), {"2026-10-22"}])
    assert booked == []


def test_allow_same_day_target_books_on_a_reserved_day_and_still_blocks_others():
    booked = _run_main(
        [_watch("lei", allow_same_day=True), _watch("ugly-baby")], resy_days={"2026-10-22"}
    )
    # lei opted out, so it takes Oct 22 despite the hand-made booking;
    # ugly-baby skips Oct 22 as usual.
    assert booked == [("lei", "2026-10-22"), ("ugly-baby", "2026-10-23")]


def test_reserved_days_keeps_last_known_list_when_resy_fails():
    reserved = main.ReservedDays({"2026-10-24"})
    with patch("main.resy_api.upcoming_reservation_days", return_value={"2026-10-22"}):
        reserved.refresh()
    with patch("main.resy_api.upcoming_reservation_days", side_effect=RuntimeError("500")):
        reserved.refresh(max_age=0)
    assert "2026-10-22" in reserved  # from Resy, kept despite the failed refresh
    assert "2026-10-24" in reserved  # from targets.json
    assert "2026-10-23" not in reserved


def test_main_respects_bookings_from_earlier_runs():
    pizza = _target(key="pizza", booking={"day": "2026-10-24", "time": "17:00"})
    with patch("main.targets_module.load", return_value=[pizza, _target(key="other")]):
        assert main.booked_days_from_targets() == {"2026-10-24"}
