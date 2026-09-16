"""Email confirmation, over Gmail SMTP.

Deliberately the same mechanism as concert-ticket-alerts/alerts.py in this
repo (Gmail address + app password), so there's one credential pattern to
maintain rather than two.

Note this does *not* go through the Gmail MCP connector: MCP tools only
exist inside a Claude session, and this service has to be able to email you
at 9am on a Saturday from Vercel or Fly with nobody watching.
"""

import logging
import os
import smtplib
import ssl
from email.mime.text import MIMEText

import sniper

logger = logging.getLogger(__name__)


def is_configured():
    return bool(os.environ.get("ALERT_EMAIL_FROM") and os.environ.get("ALERT_EMAIL_PASSWORD"))


def send_email(subject, body, extra_recipients=()):
    sender = os.environ["ALERT_EMAIL_FROM"]
    password = os.environ["ALERT_EMAIL_PASSWORD"]
    recipients = [os.environ.get("ALERT_EMAIL_TO", sender), *extra_recipients]

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())


def format_outcome(outcome):
    """Render an Outcome as (subject, body). Also used by the CLI for stdout."""
    target = outcome.target
    slot = outcome.slot

    if outcome.status == sniper.BOOKED:
        subject = f"Booked: {target.name} - {outcome.day} at {slot.time_str}"
        lines = [
            f"Table for {target.party_size} confirmed.",
            "",
            f"Restaurant:   {target.name}",
            f"Date:         {slot.start.strftime('%A, %B %-d, %Y')}",
            f"Time:         {slot.time_str}",
            f"Seating:      {slot.config_type or 'unspecified'}",
        ]
        if outcome.booking and outcome.booking.confirmation:
            lines.append(f"Confirmation: {outcome.booking.confirmation}")
        if outcome.details and outcome.details.cancellation_text:
            lines += ["", f"Cancellation policy: {outcome.details.cancellation_text}"]
        lines += [
            "",
            "Manage or cancel this reservation at https://resy.com/account/reservations",
            "(Resy sends its own confirmation email too - this one just gets to you faster.)",
        ]
        return subject, "\n".join(lines)

    if outcome.status == sniper.DRY_RUN:
        subject = f"[dry run] Would book: {target.name} - {outcome.day} at {slot.time_str}"
        body = "\n".join([
            "A matching slot was found but nothing was booked.",
            "",
            f"Restaurant: {target.name}",
            f"Date:       {outcome.day}",
            f"Time:       {slot.time_str}  ({slot.config_type or 'unspecified'})",
            "",
            "Set RESY_LIVE_BOOKING=1 to let the sniper actually book.",
        ])
        return subject, body

    if outcome.status == sniper.SKIPPED_FEE:
        # This slot costs something, so it's your call, not the bot's. The
        # email exists to give you the two numbers you need to make it.
        fee = outcome.details.cancellation_fee if outcome.details else None
        policy = (outcome.details.cancellation_text if outcome.details else "") or "not stated"
        fee_str = f"${fee:.2f}" if fee is not None else "unknown"

        subject = (
            f"Your call: {target.name} {outcome.day} at "
            f"{slot.time_str if slot else '?'} - {fee_str} to cancel"
        )
        lines = [
            "A matching slot is available, but it is not free to cancel,",
            "so nothing was booked. Your decision:",
            "",
            f"Restaurant:        {target.name}",
            f"Date:              {outcome.day}",
            f"Time:              {slot.time_str if slot else '?'}",
            f"Seating:           {slot.config_type or 'unspecified'}" if slot else "",
            "",
            f"Cancellation fee:  {fee_str}",
            f"Terms:             {policy}",
            "",
            "To take it: book by hand at https://resy.com, or ask the sniper to",
            "book this exact slot and confirm the fee when it asks.",
            "",
            f"(Free slots are booked automatically; anything above the "
            f"${target.max_cancellation_fee:.2f} ceiling comes to you like this. "
            f"Raise RESY_MAX_CANCELLATION_FEE to widen what books unattended.)",
        ]
        if not slot:
            lines = [line for line in lines if line != ""] or lines
        return subject, "\n".join(line for line in lines if line is not None)

    return (
        f"No booking: {target.name}",
        f"{outcome.status}: {outcome.reason}",
    )


def notify(outcome):
    """Email the user about an outcome worth interrupting them for.

    Returns True if an email went out. A send failure is logged, never
    raised: losing the notification is bad, but losing it *and* crashing
    after a real booking went through is worse.
    """
    if outcome.status not in (sniper.BOOKED, sniper.DRY_RUN, sniper.SKIPPED_FEE):
        return False

    if not is_configured():
        logger.warning(
            "ALERT_EMAIL_FROM/ALERT_EMAIL_PASSWORD not set - skipping email for %s",
            outcome.status,
        )
        return False

    subject, body = format_outcome(outcome)
    try:
        send_email(subject, body, getattr(outcome.target, "extra_recipients", ()))
    except Exception:
        logger.exception("Failed to send confirmation email. Outcome was: %s", subject)
        return False
    logger.info("Sent notification email: %s", subject)
    return True
