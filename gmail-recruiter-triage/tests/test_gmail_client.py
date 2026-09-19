import base64
import email
from unittest.mock import MagicMock

import pytest

import gmail_client


def _headers(**kwargs):
    return [{"name": name, "value": value} for name, value in kwargs.items()]


def _service_with_thread(headers):
    """A mock Gmail service whose threads().get() returns a one-message
    thread carrying `headers`.
    """
    service = MagicMock()
    service.users.return_value.threads.return_value.get.return_value.execute.return_value = {
        "messages": [{"payload": {"headers": headers}}]
    }
    service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
        "id": "sent-1"
    }
    return service


def _sent_message(service):
    """Parse the raw message handed to messages().send()."""
    body = service.users.return_value.messages.return_value.send.call_args.kwargs["body"]
    return email.message_from_bytes(base64.urlsafe_b64decode(body["raw"])), body


@pytest.fixture
def service(monkeypatch):
    svc = _service_with_thread(
        _headers(
            **{
                "Message-ID": "<recruiter-2@example.com>",
                "References": "<recruiter-1@example.com>",
                "Subject": "Re: Staff engineer role at Acme",
            }
        )
    )
    monkeypatch.setattr(gmail_client, "_get_service", lambda: svc)
    return svc


def test_send_reply_sets_threading_headers(service):
    gmail_client.send_reply(
        "thread-1", "r@example.com", "Re: Staff engineer role at Acme", "Thanks for reaching out."
    )

    message, body = _sent_message(service)
    assert body["threadId"] == "thread-1"
    assert message["In-Reply-To"] == "<recruiter-2@example.com>"
    # Full ancestry chain: what the replied-to message referenced, then itself.
    assert message["References"] == "<recruiter-1@example.com> <recruiter-2@example.com>"


def test_send_reply_falls_back_to_thread_subject_when_draft_drifted(service):
    gmail_client.send_reply(
        "thread-1", "r@example.com", "Following up", "Thanks for reaching out."
    )

    message, _ = _sent_message(service)
    assert message["subject"] == "Re: Staff engineer role at Acme"


def test_send_reply_keeps_matching_draft_subject(service):
    gmail_client.send_reply(
        "thread-1", "r@example.com", "RE: Staff engineer role at Acme", "Thanks."
    )

    message, _ = _sent_message(service)
    assert message["subject"] == "RE: Staff engineer role at Acme"


def test_send_reply_without_message_id_omits_headers(monkeypatch):
    svc = _service_with_thread(_headers(Subject="Staff engineer role at Acme"))
    monkeypatch.setattr(gmail_client, "_get_service", lambda: svc)

    gmail_client.send_reply("thread-1", "r@example.com", "Re: Staff engineer role at Acme", "Hi.")

    message, _ = _sent_message(svc)
    assert message["In-Reply-To"] is None
    assert message["References"] is None


def test_send_reply_marks_thread_read(service):
    gmail_client.send_reply("thread-1", "r@example.com", "Re: Staff engineer role at Acme", "Hi.")

    service.users.return_value.threads.return_value.modify.assert_called_once_with(
        userId="me", id="thread-1", body={"removeLabelIds": ["UNREAD"]}
    )


def test_get_thread_reply_headers_empty_thread(monkeypatch):
    svc = MagicMock()
    svc.users.return_value.threads.return_value.get.return_value.execute.return_value = {}
    monkeypatch.setattr(gmail_client, "_get_service", lambda: svc)

    assert gmail_client.get_thread_reply_headers("thread-1") == {
        "message_id": "",
        "references": "",
        "subject": "",
    }


@pytest.mark.parametrize(
    "subject,expected",
    [
        ("Re: Role at Acme", "Role at Acme"),
        ("RE: re: Role at Acme", "Role at Acme"),
        ("Re[2]: Role at Acme", "Role at Acme"),
        ("Role at Acme", "Role at Acme"),
        (None, ""),
    ],
)
def test_normalize_subject(subject, expected):
    assert gmail_client._normalize_subject(subject) == expected
