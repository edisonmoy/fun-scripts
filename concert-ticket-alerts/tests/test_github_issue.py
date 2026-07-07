from unittest.mock import MagicMock, patch

import github_issue


def _mock_response(json_data=None, status_ok=True):
    resp = MagicMock()
    resp.json.return_value = json_data or []
    resp.raise_for_status = MagicMock()
    return resp


def test_escalate_creates_new_issue_when_none_open(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "edisonmoy/fun-scripts")

    with patch("github_issue.requests.get", return_value=_mock_response([])) as mock_get, \
         patch("github_issue.requests.post", return_value=_mock_response()) as mock_post:
        github_issue.escalate("stubhub", "403 Forbidden")

    mock_get.assert_called_once()
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["title"] == "Scraper blocked: stubhub"
    assert "403 Forbidden" in kwargs["json"]["body"]
    assert kwargs["json"]["labels"] == ["scraper-blocked"]


def test_escalate_comments_on_existing_issue(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "edisonmoy/fun-scripts")
    existing = [{"number": 42, "title": "Scraper blocked: stubhub"}]

    with patch("github_issue.requests.get", return_value=_mock_response(existing)), \
         patch("github_issue.requests.post", return_value=_mock_response()) as mock_post:
        github_issue.escalate("stubhub", "timeout")

    args, kwargs = mock_post.call_args
    assert "issues/42/comments" in args[0]


def test_resolve_closes_existing_issue(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "edisonmoy/fun-scripts")
    existing = [{"number": 42, "title": "Scraper blocked: stubhub"}]

    with patch("github_issue.requests.get", return_value=_mock_response(existing)), \
         patch("github_issue.requests.patch", return_value=_mock_response()) as mock_patch, \
         patch("github_issue.requests.post", return_value=_mock_response()) as mock_post:
        github_issue.resolve("stubhub")

    patch_args, patch_kwargs = mock_patch.call_args
    assert "issues/42" in patch_args[0]
    assert patch_kwargs["json"] == {"state": "closed"}
    mock_post.assert_called_once()


def test_resolve_noop_when_no_open_issue(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "edisonmoy/fun-scripts")

    with patch("github_issue.requests.get", return_value=_mock_response([])), \
         patch("github_issue.requests.patch") as mock_patch, \
         patch("github_issue.requests.post") as mock_post:
        github_issue.resolve("stubhub")

    mock_patch.assert_not_called()
    mock_post.assert_not_called()
