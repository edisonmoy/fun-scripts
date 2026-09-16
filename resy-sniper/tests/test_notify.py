import notify
import runner
import sniper
from resy_api import Booking
from tests.factories import FakeClient, make_details, make_slot, make_target


def booked_outcome():
    return sniper.Outcome(
        sniper.BOOKED,
        make_target(),
        day="2026-09-19",
        slot=make_slot("19:30"),
        details=make_details(),
        booking=Booking(resy_token="tok", confirmation="ABC123"),
    )


def test_confirmation_email_contains_the_details_you_need():
    subject, body = notify.format_outcome(booked_outcome())

    assert "Booked" in subject and "7:30 PM" in subject
    assert "Saturday, September 19, 2026" in body
    assert "Table for 2" in body
    assert "ABC123" in body
    assert "Dining Room" in body


def test_dry_run_email_is_clearly_marked_as_not_booked():
    outcome = sniper.Outcome(
        sniper.DRY_RUN, make_target(), day="2026-09-19", slot=make_slot("19:30")
    )
    subject, body = notify.format_outcome(outcome)

    assert subject.startswith("[dry run]")
    assert "nothing was booked" in body
    assert "RESY_LIVE_BOOKING" in body


def test_priced_slot_email_leads_with_the_fee_and_terms():
    """The email exists so you can decide - it has to carry both numbers."""
    outcome = sniper.Outcome(
        sniper.SKIPPED_FEE,
        make_target(),
        day="2026-09-19",
        slot=make_slot("19:30"),
        details=make_details(fee=25.0),
        reason="slot carries a $25.00 cancellation fee, above the $0.00 ceiling",
    )
    subject, body = notify.format_outcome(outcome)

    # The price belongs in the subject line - that's all you see on a phone.
    assert "$25.00 to cancel" in subject
    assert "Your call" in subject

    assert "nothing was booked" in body
    assert "Cancellation fee:  $25.00" in body
    assert "Cancel 24h ahead" in body  # the actual terms, not just the number
    assert "RESY_MAX_CANCELLATION_FEE" in body


def test_priced_slot_email_survives_missing_details():
    outcome = sniper.Outcome(
        sniper.SKIPPED_FEE, make_target(), day="2026-09-19", slot=make_slot("19:30")
    )
    subject, body = notify.format_outcome(outcome)

    assert "unknown" in subject
    assert "not stated" in body


def test_no_email_for_routine_no_match(monkeypatch):
    monkeypatch.setenv("ALERT_EMAIL_FROM", "a@b.com")
    monkeypatch.setenv("ALERT_EMAIL_PASSWORD", "pw")
    outcome = sniper.Outcome(sniper.NO_MATCH, make_target(), reason="nothing available")

    assert notify.notify(outcome) is False


def test_no_email_when_credentials_are_missing(monkeypatch):
    monkeypatch.delenv("ALERT_EMAIL_FROM", raising=False)
    monkeypatch.delenv("ALERT_EMAIL_PASSWORD", raising=False)

    assert notify.notify(booked_outcome()) is False


def test_email_failure_does_not_lose_the_booking(monkeypatch):
    """A dead SMTP connection must not turn a successful booking into a crash."""
    monkeypatch.setenv("ALERT_EMAIL_FROM", "a@b.com")
    monkeypatch.setenv("ALERT_EMAIL_PASSWORD", "pw")

    def boom(*args, **kwargs):
        raise OSError("smtp down")

    monkeypatch.setattr(notify, "send_email", boom)

    assert notify.notify(booked_outcome()) is False


def test_email_is_sent_for_a_real_booking(monkeypatch):
    monkeypatch.setenv("ALERT_EMAIL_FROM", "a@b.com")
    monkeypatch.setenv("ALERT_EMAIL_PASSWORD", "pw")
    sent = {}

    monkeypatch.setattr(
        notify, "send_email", lambda s, b, r=(): sent.update(subject=s, body=b)
    )

    assert notify.notify(booked_outcome()) is True
    assert "ABC123" in sent["body"]


# --- runner ------------------------------------------------------------

def test_run_once_continues_past_a_failing_target(monkeypatch):
    good = make_target(key="good")
    bad = make_target(key="bad")

    def fake_snipe(client, target, live_booking, **kwargs):
        if target.key == "bad":
            raise RuntimeError("resy exploded")
        return sniper.Outcome(sniper.NO_MATCH, target, reason="nothing")

    monkeypatch.setattr(sniper, "snipe", fake_snipe)
    outcomes = runner.run_once(
        client=FakeClient(), live_booking=False, targets=[bad, good], send_email=False
    )

    assert [o.target.key for o in outcomes] == ["bad", "good"]
    assert "resy exploded" in outcomes[0].reason


def test_run_once_defaults_to_the_configured_booking_mode(monkeypatch):
    seen = {}

    def fake_snipe(client, target, live_booking, **kwargs):
        seen["live"] = live_booking
        return sniper.Outcome(sniper.NO_MATCH, target)

    monkeypatch.setattr(sniper, "snipe", fake_snipe)
    monkeypatch.setattr(runner.config, "LIVE_BOOKING", False)
    runner.run_once(client=FakeClient(), targets=[make_target()], send_email=False)

    assert seen["live"] is False
