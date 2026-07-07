import os
import smtplib
import ssl
from email.mime.text import MIMEText


def send_email(subject, body):
    sender = os.environ["ALERT_EMAIL_FROM"]
    password = os.environ["ALERT_EMAIL_PASSWORD"]
    recipient = os.environ.get("ALERT_EMAIL_TO", sender)

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())


def check_price_drop(
    source, price_per_ticket, floor_before, price_target_per_ticket, pct_drop_threshold,
    confidence=None, section=None, row=None,
):
    """Return an alert reason string if this price is a significant drop, else None.

    Fires on either condition: hitting the flat dollar target, or falling
    pct_drop_threshold percent below the lowest price seen so far.

    confidence="low" means the price came from the crude fallback text
    scrape rather than a real quantity-aware listing from captured JSON -
    it isn't structurally guaranteed to be for 2 seats together, so the
    reason is flagged as an unverified estimate rather than presented as
    fact.

    section/row (when known) are included so the alert is something you
    can actually go verify on the live site before trusting it - resale
    marketplaces are highly dynamic (a listing can sell or get pulled
    within minutes of being scraped) and a raw API response can include
    listings the site's own UI filters out of its default view, so even a
    "high confidence" match isn't a guarantee.
    """
    if price_per_ticket is None:
        return None

    reasons = []
    if price_per_ticket <= price_target_per_ticket:
        reasons.append(f"hit your ${price_target_per_ticket:.0f}/ticket target")

    if floor_before is not None and floor_before > 0:
        pct_drop = (floor_before - price_per_ticket) / floor_before * 100
        if pct_drop >= pct_drop_threshold:
            reasons.append(
                f"dropped {pct_drop:.0f}% below the previous floor "
                f"(${floor_before:.0f} -> ${price_per_ticket:.0f})"
            )

    if not reasons:
        return None

    reason = f"{source}: ${price_per_ticket:.0f}/ticket - " + " and ".join(reasons)
    if section or row:
        location = ", ".join(filter(None, [f"Section {section}" if section else None,
                                             f"Row {row}" if row else None]))
        reason += f" ({location} - verify this listing is still live before buying)"
    if confidence == "low":
        reason += (
            " [UNVERIFIED ESTIMATE - not confirmed as 2 seats together, "
            "double-check before buying]"
        )
    return reason
