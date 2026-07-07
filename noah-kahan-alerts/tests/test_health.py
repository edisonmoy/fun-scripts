import health


def _use_temp_health_file(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "HEALTH_PATH", str(tmp_path / "scraper_health.json"))


def test_first_failure_has_no_recovery(tmp_path, monkeypatch):
    _use_temp_health_file(tmp_path, monkeypatch)

    consecutive, just_recovered = health.record_outcome("stubhub", "blocked")

    assert consecutive == 1
    assert just_recovered is False


def test_consecutive_failures_accumulate(tmp_path, monkeypatch):
    _use_temp_health_file(tmp_path, monkeypatch)

    for _ in range(3):
        consecutive, _ = health.record_outcome("stubhub", "blocked")

    assert consecutive == 3


def test_error_status_also_counts_as_failure(tmp_path, monkeypatch):
    _use_temp_health_file(tmp_path, monkeypatch)

    health.record_outcome("stubhub", "blocked")
    consecutive, _ = health.record_outcome("stubhub", "error")

    assert consecutive == 2


def test_ok_after_failures_resets_and_flags_recovery(tmp_path, monkeypatch):
    _use_temp_health_file(tmp_path, monkeypatch)

    health.record_outcome("stubhub", "blocked")
    health.record_outcome("stubhub", "blocked")
    consecutive, just_recovered = health.record_outcome("stubhub", "ok")

    assert consecutive == 0
    assert just_recovered is True


def test_ok_with_no_prior_failures_is_not_a_recovery(tmp_path, monkeypatch):
    _use_temp_health_file(tmp_path, monkeypatch)

    consecutive, just_recovered = health.record_outcome("stubhub", "ok")

    assert consecutive == 0
    assert just_recovered is False


def test_sources_are_tracked_independently(tmp_path, monkeypatch):
    _use_temp_health_file(tmp_path, monkeypatch)

    health.record_outcome("stubhub", "blocked")
    health.record_outcome("stubhub", "blocked")
    consecutive_vividseats, _ = health.record_outcome("vividseats", "blocked")

    assert consecutive_vividseats == 1
