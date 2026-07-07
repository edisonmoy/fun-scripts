import seatgeek_api
import storage
import supply_demand

EVENT_KEY = "test-event"


def test_build_signal_none_when_target_event_missing():
    snapshots = [{"id": 1, "lowest_price": 500, "venue": "Somewhere"}]

    assert supply_demand.build_signal(EVENT_KEY, snapshots, target_event_id=999) is None


def test_build_signal_none_when_target_has_no_price():
    snapshots = [{"id": 1, "lowest_price": None, "venue": "Somewhere"}]

    assert supply_demand.build_signal(EVENT_KEY, snapshots, target_event_id=1) is None


def test_build_signal_compares_against_tour_median(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    snapshots = [
        {"id": 1, "lowest_price": 700, "venue": "Some Stadium"},
        {"id": 2, "lowest_price": 400, "venue": "Another Venue"},
        {"id": 3, "lowest_price": 500, "venue": "Third Venue"},
    ]

    signal = supply_demand.build_signal(EVENT_KEY, snapshots, target_event_id=1)

    assert signal is not None
    assert "above" in signal
    assert "median" in signal


def test_build_signal_reports_price_trend_from_history(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    storage.append_record(f"{EVENT_KEY}__tour_event_1", {"lowest_price": 700, "listing_count": 50})
    storage.append_record(f"{EVENT_KEY}__tour_event_1", {"lowest_price": 560, "listing_count": 50})

    snapshots = [{"id": 1, "lowest_price": 560, "venue": "Some Stadium"}]

    signal = supply_demand.build_signal(EVENT_KEY, snapshots, target_event_id=1)

    assert "Price trend" in signal
    assert "down 20%" in signal


def test_build_signal_reports_listing_trend_from_history(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    storage.append_record(f"{EVENT_KEY}__tour_event_1", {"lowest_price": 700, "listing_count": 20})
    storage.append_record(f"{EVENT_KEY}__tour_event_1", {"lowest_price": 700, "listing_count": 30})

    snapshots = [{"id": 1, "lowest_price": 700, "venue": "Some Stadium"}]

    signal = supply_demand.build_signal(EVENT_KEY, snapshots, target_event_id=1)

    assert "Inventory trend" in signal
    assert "supply loosening" in signal


def test_snapshot_tour_logs_history_and_returns_records(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))

    fake_events = [
        {
            "id": 1,
            "title": "Some Artist at Some Stadium",
            "datetime_utc": "2026-07-19T22:30:00",
            "venue": {"name": "Some Stadium", "city": "Some City"},
            "stats": {"lowest_price": 500, "median_price": 650, "listing_count": 40},
        }
    ]
    monkeypatch.setattr(seatgeek_api, "get_tour_events", lambda slug: fake_events)

    snapshots = supply_demand.snapshot_tour(EVENT_KEY, "some-artist")

    assert len(snapshots) == 1
    assert snapshots[0]["lowest_price"] == 500
    assert storage.load_records(f"{EVENT_KEY}__tour_event_1")[0]["lowest_price"] == 500
