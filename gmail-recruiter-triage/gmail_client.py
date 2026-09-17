import base64
import os
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime

import google.auth.transport.requests
import google.oauth2.credentials
from googleapiclient.discovery import build

import config

TOKEN_URI = "https://oauth2.googleapis.com/token"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]


def _get_credentials():
    creds = google.oauth2.credentials.Credentials(
        token=None,
        refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
        token_uri=TOKEN_URI,
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    creds.refresh(google.auth.transport.requests.Request())
    return creds


def _get_service():
    return build("gmail", "v1", credentials=_get_credentials(), cache_discovery=False)


def search_candidate_threads(query, after_date=None):
    """Search Gmail for candidate thread ids matching `query`, received on
    or after `after_date` (a datetime; defaults to
    config.DEFAULT_LOOKBACK_DAYS ago when None - e.g. on the first ever
    run, before run_state.last_run_at is set).

    Note: Gmail's `after:` search operator is date-granularity only (no
    time-of-day), so this can re-surface threads from earlier the same
    calendar day as the last run - is_thread_processed() is what actually
    dedupes those against previously-processed threads.
    """
    if after_date is None:
        after_date = datetime.now(timezone.utc) - timedelta(days=config.DEFAULT_LOOKBACK_DAYS)

    full_query = f"{query} after:{after_date.strftime('%Y/%m/%d')}"
    service = _get_service()

    thread_ids = []
    page_token = None
    while True:
        response = (
            service.users()
            .threads()
            .list(userId="me", q=full_query, pageToken=page_token)
            .execute()
        )
        thread_ids.extend(t["id"] for t in response.get("threads", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return thread_ids


def _decode_body(data):
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _extract_plaintext_part(payload):
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return _decode_body(payload["body"]["data"])

    for part in payload.get("parts", []):
        text = _extract_plaintext_part(part)
        if text:
            return text

    return ""


def get_thread_plaintext(thread_id):
    """Fetch a Gmail thread and return the most recent message's plaintext.

    Returns {"sender": str, "subject": str, "received_at": datetime | None,
    "body": str}.
    """
    service = _get_service()
    thread = service.users().threads().get(userId="me", id=thread_id, format="full").execute()
    messages = thread.get("messages", [])
    if not messages:
        return {"sender": "", "subject": "", "received_at": None, "body": ""}

    message = messages[-1]
    headers = {
        h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])
    }

    received_at = None
    if "date" in headers:
        try:
            received_at = parsedate_to_datetime(headers["date"])
        except (TypeError, ValueError):
            received_at = None

    body = _extract_plaintext_part(message.get("payload", {}))

    return {
        "sender": headers.get("from", ""),
        "subject": headers.get("subject", ""),
        "received_at": received_at,
        "body": body,
    }


def ensure_label(name):
    """Return the id of the Gmail label `name`, creating it as a visible
    user label if it doesn't already exist.
    """
    service = _get_service()
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for label in labels:
        if label["name"] == name:
            return label["id"]

    created = (
        service.users()
        .labels()
        .create(
            userId="me",
            body={
                "name": name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        )
        .execute()
    )
    return created["id"]


def apply_label(thread_id, label_id):
    service = _get_service()
    service.users().threads().modify(
        userId="me", id=thread_id, body={"addLabelIds": [label_id]}
    ).execute()


def send_reply(thread_id, to, subject, body):
    """Send a new message as a reply within `thread_id`. Returns the sent
    message's id.

    Deliberately does not create a Gmail draft first - Edison reviews and
    approves drafts in the dashboard (backed by Postgres), not in Gmail's
    own Drafts folder, so there's no need to also clutter Gmail with a
    draft object before actually sending.
    """
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

    service = _get_service()
    sent = (
        service.users()
        .messages()
        .send(userId="me", body={"raw": raw, "threadId": thread_id})
        .execute()
    )

    # Edison has now replied - the thread shouldn't linger in the inbox as
    # unread just because the reply came from an API call instead of Gmail
    # itself.
    service.users().threads().modify(
        userId="me", id=thread_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()

    return sent["id"]
