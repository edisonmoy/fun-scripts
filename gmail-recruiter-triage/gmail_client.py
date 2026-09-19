import base64
import os
import re
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


def _normalize_subject(subject):
    """Strip any leading Re:/RE:/Re[2]: prefixes, for comparing a drafted
    subject against the thread's own subject.
    """
    stripped = re.sub(
        r"^\s*(re\s*(\[\d+\])?\s*:\s*)+", "", subject or "", flags=re.IGNORECASE
    )
    return stripped.strip()


def get_thread_reply_headers(thread_id):
    """Return the headers needed to make a reply thread correctly in the
    RECIPIENT's mail client, not just in Edison's Gmail.

    Gmail's `threadId` only files the sent message into Edison's own copy
    of the thread. The recruiter's client (Outlook, Superhuman, another
    Gmail account) threads on RFC 5322 `In-Reply-To`/`References` instead,
    so without those headers the reply lands as a standalone message and
    the recruiter's response comes back as a brand new thread. Gmail also
    requires the sent message's subject to match the thread's, or it
    silently breaks the thread on Edison's side too.

    Returns {"message_id": str, "references": str, "subject": str} taken
    from the thread's most recent message; empty strings when unavailable.
    """
    service = _get_service()
    thread = (
        service.users()
        .threads()
        .get(
            userId="me",
            id=thread_id,
            format="metadata",
            metadataHeaders=["Message-ID", "References", "Subject"],
        )
        .execute()
    )
    messages = thread.get("messages", [])
    if not messages:
        return {"message_id": "", "references": "", "subject": ""}

    headers = {
        h["name"].lower(): h["value"] for h in messages[-1].get("payload", {}).get("headers", [])
    }
    message_id = headers.get("message-id", "")
    prior_references = headers.get("references", "")

    # References is the full ancestry chain: everything the message we're
    # replying to already referenced, plus that message itself.
    references = " ".join(part for part in (prior_references, message_id) if part)

    return {
        "message_id": message_id,
        "references": references,
        "subject": headers.get("subject", ""),
    }


def send_reply(thread_id, to, subject, body):
    """Send a new message as a reply within `thread_id`. Returns the sent
    message's id.

    The message carries `In-Reply-To`/`References` pointing at the thread's
    most recent message, and a subject matching that thread, so the
    recruiter's reply to it stays in the same conversation rather than
    starting a fresh thread (see get_thread_reply_headers).

    Deliberately does not create a Gmail draft first - Edison reviews and
    approves drafts in the dashboard (backed by Postgres), not in Gmail's
    own Drafts folder, so there's no need to also clutter Gmail with a
    draft object before actually sending.
    """
    service = _get_service()
    reply_headers = get_thread_reply_headers(thread_id)

    # The drafted subject is model- or template-generated, so it can drift
    # from the thread's actual subject. Gmail needs them to match (modulo
    # the Re: prefix) to keep the message in the thread, and so does every
    # other client's subject-based threading fallback, so the thread's own
    # subject wins whenever they differ.
    thread_subject = reply_headers["subject"]
    if thread_subject and _normalize_subject(subject) != _normalize_subject(thread_subject):
        subject = f"Re: {_normalize_subject(thread_subject)}"

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    if reply_headers["message_id"]:
        message["In-Reply-To"] = reply_headers["message_id"]
    if reply_headers["references"]:
        message["References"] = reply_headers["references"]
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

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
