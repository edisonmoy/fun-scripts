import json

import pytest

import targets


def _write(tmp_path, entries):
    path = tmp_path / "targets.json"
    path.write_text(json.dumps(entries))
    return str(path)


def test_load_applies_defaults(tmp_path):
    path = _write(tmp_path, [
        {"key": "a", "venue_name": "Pizza 4P's Brooklyn", "request": "Saturday dinner for 2"}
    ])

    loaded = targets.load(path)

    assert len(loaded) == 1
    t = loaded[0]
    assert t.key == "a"
    assert t.venue_id is None
    assert t.party_size_override is None
    assert t.enabled is True
    assert t.dry_run is None
    assert t.booking is None


def test_load_respects_explicit_fields(tmp_path):
    path = _write(tmp_path, [
        {
            "key": "a",
            "venue_name": "Pizza 4P's Brooklyn",
            "venue_id": 98384,
            "request": "Saturday dinner for 2",
            "party_size_override": 4,
            "enabled": False,
            "dry_run": True,
        }
    ])

    loaded = targets.load(path)

    assert loaded[0].venue_id == 98384
    assert loaded[0].party_size_override == 4
    assert loaded[0].enabled is False
    assert loaded[0].dry_run is True


def test_load_multiple_targets(tmp_path):
    path = _write(tmp_path, [
        {"key": "a", "venue_name": "Venue A", "request": "req a"},
        {"key": "b", "venue_name": "Venue B", "request": "req b"},
    ])

    loaded = targets.load(path)

    assert [t.key for t in loaded] == ["a", "b"]


def test_load_rejects_duplicate_keys(tmp_path):
    path = _write(tmp_path, [
        {"key": "a", "venue_name": "Venue A", "request": "req a"},
        {"key": "a", "venue_name": "Venue B", "request": "req b"},
    ])

    with pytest.raises(ValueError):
        targets.load(path)


def test_load_reads_booking_field(tmp_path):
    path = _write(tmp_path, [
        {
            "key": "a",
            "venue_name": "Venue A",
            "request": "req a",
            "booking": {"day": "2026-09-19", "time": "17:00", "reservation_id": "abc123"},
        }
    ])

    loaded = targets.load(path)

    assert loaded[0].booking == {"day": "2026-09-19", "time": "17:00", "reservation_id": "abc123"}
