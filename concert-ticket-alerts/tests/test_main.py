from unittest.mock import patch

import config
import health
import main
import seatgeek_api
import storage

EVENT = config.WATCHED_EVENTS[0]


def _reset_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(health, "HEALTH_PATH", str(tmp_path / "scraper_health.json"))


def test_check_seatgeek_uses_api_when_configured(tmp_path, monkeypatch):
    _reset_storage(tmp_path, monkeypatch)
    monkeypatch.setenv("SEATGEEK_CLIENT_ID", "fake-id")

    with patch(
        "seatgeek_api.get_event_stats", return_value={"lowest_price": 450}
    ) as m_api, patch("scrapers.seatgeek.check_price") as m_scrape:
        results, reasons = [], []
        main.check_seatgeek(EVENT, results, reasons)

    assert m_api.called
    assert not m_scrape.called
    assert results == [("seatgeek (api)", "ok", 450)]


def test_check_seatgeek_falls_back_when_not_configured(tmp_path, monkeypatch):
    _reset_storage(tmp_path, monkeypatch)
    monkeypatch.delenv("SEATGEEK_CLIENT_ID", raising=False)

    with patch(
        "scrapers.seatgeek.check_price",
        return_value={
            "price_per_ticket": 470, "status": "ok", "confidence": "high", "diagnostic": ""
        },
    ) as m_scrape:
        results, reasons = [], []
        main.check_seatgeek(EVENT, results, reasons)

    assert m_scrape.called
    assert results == [("seatgeek (scraped)", "ok", 470)]


def test_check_seatgeek_falls_back_when_api_raises(tmp_path, monkeypatch):
    _reset_storage(tmp_path, monkeypatch)
    monkeypatch.setenv("SEATGEEK_CLIENT_ID", "fake-id")

    with patch(
        "seatgeek_api.get_event_stats", side_effect=RuntimeError("rate limited")
    ), patch(
        "scrapers.seatgeek.check_price",
        return_value={
            "price_per_ticket": 480, "status": "fallback", "confidence": "low", "diagnostic": ""
        },
    ) as m_scrape:
        results, reasons = [], []
        main.check_seatgeek(EVENT, results, reasons)

    assert m_scrape.called
    assert results == [("seatgeek (scraped)", "fallback", 480)]


def test_check_seatgeek_scraped_fallback_flags_low_confidence_alerts(tmp_path, monkeypatch):
    _reset_storage(tmp_path, monkeypatch)
    monkeypatch.delenv("SEATGEEK_CLIENT_ID", raising=False)
    storage.append_record(f"{EVENT.key}__seatgeek", {"price_per_ticket": 900})

    with patch(
        "scrapers.seatgeek.check_price",
        return_value={
            "price_per_ticket": 400, "status": "fallback", "confidence": "low", "diagnostic": ""
        },
    ):
        results, reasons = [], []
        main.check_seatgeek(EVENT, results, reasons)

    assert len(reasons) == 1
    assert "UNVERIFIED ESTIMATE" in reasons[0]


def test_seatgeek_api_and_scraped_prices_share_one_price_history(tmp_path, monkeypatch):
    # confirms the floor/trend stays continuous regardless of which method
    # produced a given reading
    _reset_storage(tmp_path, monkeypatch)

    monkeypatch.setenv("SEATGEEK_CLIENT_ID", "fake-id")
    with patch("seatgeek_api.get_event_stats", return_value={"lowest_price": 450}):
        main.check_seatgeek(EVENT, [], [])

    monkeypatch.delenv("SEATGEEK_CLIENT_ID", raising=False)
    with patch(
        "scrapers.seatgeek.check_price",
        return_value={
            "price_per_ticket": 470, "status": "ok", "confidence": "high", "diagnostic": ""
        },
    ):
        main.check_seatgeek(EVENT, [], [])

    assert storage.running_floor(f"{EVENT.key}__seatgeek") == 450
    assert seatgeek_api.is_configured() is False
