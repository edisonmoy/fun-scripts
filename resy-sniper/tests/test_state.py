import state


def test_is_booked_false_when_no_state_file(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "STATE_PATH", str(tmp_path / "state.json"))
    assert state.is_booked("some-target") is False


def test_mark_booked_then_is_booked(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "STATE_PATH", str(tmp_path / "state.json"))

    state.mark_booked("target-a", "2026-09-19", "19:00", "resy-token-123")

    assert state.is_booked("target-a") is True
    assert state.get_booking("target-a") == {
        "day": "2026-09-19", "time": "19:00", "reservation_id": "resy-token-123"
    }


def test_targets_are_independent(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "STATE_PATH", str(tmp_path / "state.json"))

    state.mark_booked("target-a", "2026-09-19", "19:00", "resy-token-a")

    assert state.is_booked("target-a") is True
    assert state.is_booked("target-b") is False
    assert state.get_booking("target-b") is None
