import pytest

from availability import AvailabilityError, extract_showtime

# Shape confirmed live from filmlinc.org's embedded showtime JSON for
# performance 84536 on 2026-09-24 (sold out, standby only).
SOLD_OUT_SNIPPET = (
    '{"id":"84536","productionSeasonId":"84535","date":"2026-10-01","time":"9:15 PM",'
    '"venue":"Alice Tully Hall","available":false,'
    '"ticketsUrl":"https://purchase.filmlinc.org/84535/84536","openCaptions":false,'
    '"memberBenefitsEligible":false,"freeEvent":false,"specialEvent":false,"noStandby":false,'
    '"facilityId":5,"status":"standby","description":"Cameron Winter at Carnegie",'
    '"presaleSchedule":{"presaleType":"nyff","saleDates":[{"datetime":"2026-09-15T12:00:00"}]}}'
)

AVAILABLE_SNIPPET = SOLD_OUT_SNIPPET.replace('"available":false', '"available":true').replace(
    '"status":"standby"', '"status":"onsale"'
)


def test_extract_showtime_sold_out():
    html = f"<script>{SOLD_OUT_SNIPPET}</script>"
    showtime = extract_showtime(html, "84536")
    assert showtime["available"] is False
    assert showtime["status"] == "standby"
    assert showtime["date"] == "2026-10-01"
    assert showtime["time"] == "9:15 PM"
    assert showtime["tickets_url"] == "https://purchase.filmlinc.org/84535/84536"


def test_extract_showtime_available():
    html = f"<script>{AVAILABLE_SNIPPET}</script>"
    showtime = extract_showtime(html, "84536")
    assert showtime["available"] is True
    assert showtime["status"] == "onsale"


def test_extract_showtime_missing_performance_returns_none():
    html = f"<script>{SOLD_OUT_SNIPPET}</script>"
    assert extract_showtime(html, "99999") is None


def test_extract_showtime_unparseable_fields_raises():
    html = '<script>{"id":"84536","somethingElseEntirely":true}</script>'
    with pytest.raises(AvailabilityError):
        extract_showtime(html, "84536")
