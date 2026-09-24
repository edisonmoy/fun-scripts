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
