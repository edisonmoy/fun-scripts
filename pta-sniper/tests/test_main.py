from unittest.mock import patch

import main


def _showtime(**overrides):
    defaults = dict(
        performance_id="84536",
        available=True,
        status="onsale",
        date="2026-10-01",
        time="9:15 PM",
        venue="Alice Tully Hall",
        tickets_url="https://purchase.filmlinc.org/84535/84536",
    )
    defaults.update(overrides)
    return defaults


def test_handle_opening_dry_run_alerts_but_never_attempts_purchase():
    with patch("main.config.DRY_RUN", True), \
         patch("main.alerts.send_email") as send_email, \
         patch("main.checkout.attempt_purchase") as attempt_purchase:
        booked = main.handle_opening(_showtime())

    assert booked is False
    attempt_purchase.assert_not_called()
    send_email.assert_called_once()
    assert "may be open" in send_email.call_args.kwargs["subject"]


def test_handle_opening_live_run_success_sends_confirmation():
    with patch("main.config.DRY_RUN", False), \
         patch("main.config.TICKET_QUANTITY", 2), \
         patch("main.alerts.send_email") as send_email, \
         patch("main.checkout.attempt_purchase", return_value=(True, "done")):
        booked = main.handle_opening(_showtime())

    assert booked is True
    subjects = [call.kwargs["subject"] for call in send_email.call_args_list]
    assert any("BOUGHT" in s for s in subjects)


def test_handle_opening_live_run_failure_sends_failure_alert_not_booked():
    with patch("main.config.DRY_RUN", False), \
         patch("main.config.TICKET_QUANTITY", 2), \
         patch("main.alerts.send_email") as send_email, \
         patch("main.checkout.attempt_purchase", return_value=(False, "buy widget never rendered")):
        booked = main.handle_opening(_showtime())

    assert booked is False
    subjects = [call.kwargs["subject"] for call in send_email.call_args_list]
    assert any("FAILED" in s for s in subjects)
