from datetime import datetime, timezone

import db_client


class FakeCursor:
    def __init__(self, fetchone_value=None, fetchall_value=None):
        self.executed = []
        self._fetchone_value = fetchone_value
        self._fetchall_value = fetchall_value if fetchall_value is not None else []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self._fetchone_value

    def fetchall(self):
        return self._fetchall_value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor


def _install_fake_connection(monkeypatch, fetchone_value=None, fetchall_value=None):
    cursor = FakeCursor(fetchone_value=fetchone_value, fetchall_value=fetchall_value)
    conn = FakeConnection(cursor)
    monkeypatch.setattr(db_client, "_connection", conn)
    # Skip schema application - it's a real .sql file execution, irrelevant here.
    monkeypatch.setattr(db_client, "_schema_applied", True)
    return conn, cursor


def test_is_thread_processed_true(monkeypatch):
    _install_fake_connection(monkeypatch, fetchone_value={"?column?": 1})
    assert db_client.is_thread_processed("thread-1") is True


def test_is_thread_processed_false(monkeypatch):
    _install_fake_connection(monkeypatch, fetchone_value=None)
    assert db_client.is_thread_processed("thread-1") is False


def test_get_preferences_returns_row(monkeypatch):
    row = {"target_areas": "healthcare AI", "autonomy_keep_warm": "draft_only"}
    _install_fake_connection(monkeypatch, fetchone_value=row)
    assert db_client.get_preferences() == row


def test_upsert_triage_record_returns_id(monkeypatch):
    _, cursor = _install_fake_connection(monkeypatch, fetchone_value={"id": 42})

    record_id = db_client.upsert_triage_record(
        thread_id="thread-1",
        received_at=None,
        sender="a@b.com",
        subject="Role at Acme",
        category="keep_warm",
        extracted={"company": "Acme"},
        rationale="generic recruiter outreach",
        gmail_draft_id=None,
        status="drafted",
    )

    assert record_id == 42
    query, params = cursor.executed[-1]
    assert "INSERT INTO triage_records" in query
    assert "ON CONFLICT (gmail_thread_id)" in query
    assert params[0] == "thread-1"


def test_get_approved_pending_returns_rows(monkeypatch):
    rows = [{"id": 1, "gmail_draft_id": "d1"}]
    _install_fake_connection(monkeypatch, fetchall_value=rows)
    assert db_client.get_approved_pending() == rows


def test_mark_sent_executes_update(monkeypatch):
    _, cursor = _install_fake_connection(monkeypatch)
    db_client.mark_sent(42)
    query, params = cursor.executed[-1]
    assert "UPDATE triage_records" in query
    assert "sent" in query
    assert params == (42,)


def test_get_last_run_at_returns_none_when_no_row(monkeypatch):
    _install_fake_connection(monkeypatch, fetchone_value=None)
    assert db_client.get_last_run_at() is None


def test_get_last_run_at_returns_value(monkeypatch):
    dt = datetime(2026, 9, 1, tzinfo=timezone.utc)
    _install_fake_connection(monkeypatch, fetchone_value={"last_run_at": dt})
    assert db_client.get_last_run_at() == dt


def test_set_last_run_at_executes_update(monkeypatch):
    _, cursor = _install_fake_connection(monkeypatch)
    dt = datetime.now(timezone.utc)
    db_client.set_last_run_at(dt)
    query, params = cursor.executed[-1]
    assert "UPDATE run_state" in query
    assert params == (dt,)
