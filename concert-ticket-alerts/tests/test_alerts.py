import alerts

PRICE_TARGET = 500
PCT_DROP_THRESHOLD = 15


def test_no_alert_when_price_is_none():
    reason = alerts.check_price_drop(
        "test", None, floor_before=680,
        price_target_per_ticket=PRICE_TARGET, pct_drop_threshold=PCT_DROP_THRESHOLD,
    )
    assert reason is None


def test_no_alert_for_small_drop():
    reason = alerts.check_price_drop(
        "test", 670, floor_before=680,
        price_target_per_ticket=PRICE_TARGET, pct_drop_threshold=PCT_DROP_THRESHOLD,
    )
    assert reason is None


def test_alert_on_percent_drop_from_floor():
    reason = alerts.check_price_drop(
        "test", 550, floor_before=680,
        price_target_per_ticket=PRICE_TARGET, pct_drop_threshold=PCT_DROP_THRESHOLD,
    )

    assert reason is not None
    assert "19%" in reason
    assert "$680" in reason and "$550" in reason


def test_alert_on_flat_dollar_target():
    reason = alerts.check_price_drop(
        "test", 495, floor_before=680,
        price_target_per_ticket=PRICE_TARGET, pct_drop_threshold=PCT_DROP_THRESHOLD,
    )

    assert reason is not None
    assert "target" in reason
    assert "%" in reason  # both conditions fire together here


def test_alert_with_no_prior_floor():
    # first-ever reading, no floor yet: only the dollar target can fire
    reason = alerts.check_price_drop(
        "test", 400, floor_before=None,
        price_target_per_ticket=PRICE_TARGET, pct_drop_threshold=PCT_DROP_THRESHOLD,
    )

    assert reason is not None
    assert "target" in reason


def test_alert_uses_event_specific_thresholds():
    # a different event with a much lower target shouldn't fire at a price
    # that would trigger the default-style thresholds above
    reason = alerts.check_price_drop(
        "test", 90, floor_before=100,
        price_target_per_ticket=50, pct_drop_threshold=PCT_DROP_THRESHOLD,
    )
    assert reason is None


def test_low_confidence_price_is_flagged_as_unverified():
    # a price from the text-fallback scrape isn't guaranteed to be for 2
    # seats together (it could be a single-ticket price) - the alert must
    # say so rather than presenting it as a confirmed pair price
    reason = alerts.check_price_drop(
        "test", 390, floor_before=680,
        price_target_per_ticket=PRICE_TARGET, pct_drop_threshold=PCT_DROP_THRESHOLD,
        confidence="low",
    )
    assert reason is not None
    assert "UNVERIFIED ESTIMATE" in reason


def test_high_confidence_price_is_not_flagged():
    reason = alerts.check_price_drop(
        "test", 390, floor_before=680,
        price_target_per_ticket=PRICE_TARGET, pct_drop_threshold=PCT_DROP_THRESHOLD,
        confidence="high",
    )
    assert reason is not None
    assert "UNVERIFIED ESTIMATE" not in reason
