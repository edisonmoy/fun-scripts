import base64
import json
from unittest.mock import MagicMock, patch

import pytest

import github_sync


def _fetch_response(targets, sha):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    content = base64.b64encode(json.dumps(targets).encode("utf-8")).decode("utf-8")
    resp.json.return_value = {"content": content, "sha": sha}
    return resp


def test_headers_raises_when_token_missing(monkeypatch):
    import config
    monkeypatch.setattr(config, "GITHUB_TOKEN", None)

    with pytest.raises(RuntimeError):
        github_sync._headers()


def test_record_booking_sets_field_and_commits(monkeypatch):
    import config
    monkeypatch.setattr(config, "GITHUB_TOKEN", "tok")

    targets = [{"key": "a", "venue_name": "Venue A", "request": "req"}]
    get_resp = _fetch_response(targets, sha="sha1")
    put_resp = MagicMock()
    put_resp.status_code = 200
    put_resp.raise_for_status = MagicMock()

    with patch("github_sync.requests.get", return_value=get_resp) as mock_get, \
         patch("github_sync.requests.put", return_value=put_resp) as mock_put:
        github_sync.record_booking("a", "2026-09-19", "17:00", "resy-token-1")

    mock_get.assert_called_once()
    put_kwargs = mock_put.call_args.kwargs
    assert put_kwargs["json"]["sha"] == "sha1"
    committed = json.loads(base64.b64decode(put_kwargs["json"]["content"]))
    assert committed[0]["booking"] == {
        "day": "2026-09-19", "time": "17:00", "reservation_id": "resy-token-1"
    }


def test_record_booking_skips_unknown_key(monkeypatch):
    import config
    monkeypatch.setattr(config, "GITHUB_TOKEN", "tok")

    targets = [{"key": "a", "venue_name": "Venue A", "request": "req"}]
    get_resp = _fetch_response(targets, sha="sha1")

    with patch("github_sync.requests.get", return_value=get_resp), \
         patch("github_sync.requests.put") as mock_put:
        github_sync.record_booking("nonexistent", "2026-09-19", "17:00", "resy-token-1")

    mock_put.assert_not_called()


def test_record_booking_retries_on_conflict(monkeypatch):
    import config
    monkeypatch.setattr(config, "GITHUB_TOKEN", "tok")

    targets = [{"key": "a", "venue_name": "Venue A", "request": "req"}]
    get_resp_1 = _fetch_response(targets, sha="sha1")
    get_resp_2 = _fetch_response(targets, sha="sha2")

    conflict_resp = MagicMock()
    conflict_resp.status_code = 409
    success_resp = MagicMock()
    success_resp.status_code = 200
    success_resp.raise_for_status = MagicMock()

    with patch("github_sync.requests.get", side_effect=[get_resp_1, get_resp_2]), \
         patch("github_sync.requests.put", side_effect=[conflict_resp, success_resp]) as mock_put:
        github_sync.record_booking("a", "2026-09-19", "17:00", "resy-token-1")

    assert mock_put.call_count == 2
    assert mock_put.call_args_list[1].kwargs["json"]["sha"] == "sha2"
