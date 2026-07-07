import alerts
import config


def test_no_alert_when_price_is_none():
    assert alerts.check_price_drop("test", None, floor_before=680) is None


def test_no_alert_for_small_drop(monkeypatch):
    monkeypatch.setattr(config, "PRICE_TARGET_PER_TICKET", 500)
    monkeypatch.setattr(config, "PCT_DROP_THRESHOLD", 15)

    assert alerts.check_price_drop("test", 670, floor_before=680) is None


def test_alert_on_percent_drop_from_floor(monkeypatch):
    monkeypatch.setattr(config, "PRICE_TARGET_PER_TICKET", 500)
    monkeypatch.setattr(config, "PCT_DROP_THRESHOLD", 15)

    reason = alerts.check_price_drop("test", 550, floor_before=680)

    assert reason is not None
    assert "19%" in reason
    assert "$680" in reason and "$550" in reason


def test_alert_on_flat_dollar_target(monkeypatch):
    monkeypatch.setattr(config, "PRICE_TARGET_PER_TICKET", 500)
    monkeypatch.setattr(config, "PCT_DROP_THRESHOLD", 15)

    reason = alerts.check_price_drop("test", 495, floor_before=680)

    assert reason is not None
    assert "target" in reason
    assert "%" in reason  # both conditions fire together here


def test_alert_with_no_prior_floor(monkeypatch):
    monkeypatch.setattr(config, "PRICE_TARGET_PER_TICKET", 500)
    monkeypatch.setattr(config, "PCT_DROP_THRESHOLD", 15)

    # first-ever reading, no floor yet: only the dollar target can fire
    reason = alerts.check_price_drop("test", 400, floor_before=None)

    assert reason is not None
    assert "target" in reason
