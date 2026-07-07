import storage


def test_running_floor_empty_when_no_history():
    assert storage.running_floor("nonexistent_source") is None


def test_append_and_load_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))

    storage.append_record("test_source", {"price_per_ticket": 700})
    storage.append_record("test_source", {"price_per_ticket": 680})

    records = storage.load_records("test_source")

    assert [r["price_per_ticket"] for r in records] == [700, 680]
    assert all("checked_at" in r for r in records)


def test_running_floor_is_the_minimum_seen(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))

    storage.append_record("test_source", {"price_per_ticket": 700})
    storage.append_record("test_source", {"price_per_ticket": 550})
    storage.append_record("test_source", {"price_per_ticket": 620})

    assert storage.running_floor("test_source") == 550


def test_running_floor_ignores_missing_field(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))

    storage.append_record("test_source", {"something_else": 1})

    assert storage.running_floor("test_source") is None
