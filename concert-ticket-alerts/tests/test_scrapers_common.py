import re
from unittest.mock import MagicMock, patch

from scrapers import common


class TestLaunchBrowser:
    def test_prefers_real_chrome_channel(self):
        mock_p = MagicMock()

        common._launch_browser(mock_p)

        assert mock_p.chromium.launch.call_args.kwargs.get("channel") == "chrome"

    def test_falls_back_to_bundled_chromium_when_chrome_unavailable(self):
        mock_p = MagicMock()
        mock_p.chromium.launch.side_effect = [Exception("not found"), MagicMock()]

        common._launch_browser(mock_p)

        calls = mock_p.chromium.launch.call_args_list
        assert len(calls) == 2
        assert calls[0].kwargs.get("channel") == "chrome"
        assert "channel" not in calls[1].kwargs


class TestLowestSanePrice:
    def test_ignores_fees_and_parking(self):
        text = (
            "Parking Pass $45\n"
            "Sec 100 Row A $712.50 each\n"
            "Sec 200 Row F $489 each\n"
            "Sec 300 Row Z $8,950 VIP Package\n"
            "Service fee $12\n"
        )

        assert common.lowest_sane_price(text) == 489.0

    def test_respects_upper_and_lower_bounds(self):
        text = "Junk $1\nTicket $600\nToo expensive $9999999\n"

        assert common.lowest_sane_price(text) == 600.0

    def test_returns_none_when_nothing_plausible(self):
        assert common.lowest_sane_price("no prices here") is None

    def test_handles_comma_thousands_separator(self):
        assert common.lowest_sane_price("Sec 1 $1,250 each") == 1250.0

    def test_ignores_price_range_summary_line(self):
        # a filter-bar range like "$390 - $3,052+" is a site-wide min/max,
        # not an individual listing - confirmed against the real Vivid
        # Seats page, which shows this regardless of the quantity filter
        text = "$390 - $3,052+\nRow 11 | 2 tickets\n$599 ea\n"

        assert common.lowest_sane_price(text) == 599.0


class TestBlockDetection:
    def test_detects_http_status_codes(self):
        assert common._looks_blocked(403, "anything") is True
        assert common._looks_blocked(429, "anything") is True
        assert common._looks_blocked(503, "anything") is True

    def test_detects_challenge_page_text(self):
        assert common._looks_blocked(200, "Please verify you are a human before continuing") is True
        assert common._looks_blocked(200, "Pardon the interruption...") is True

    def test_normal_page_is_not_blocked(self):
        assert common._looks_blocked(200, "Sec 100 Row A $489 each") is False


class TestExtractListings:
    def test_finds_nested_listing_with_price_and_quantity(self):
        payload = {
            "data": {
                "event": {
                    "listings": [
                        {"sellerPrice": {"amount": 712.5}, "availableQuantity": 1},
                        {"sellerPrice": {"amount": 489.0}, "availableQuantity": 2},
                    ]
                }
            }
        }

        listings = common.extract_listings(payload)

        assert len(listings) == 2
        assert listings[1]["price_per_ticket"] == 489.0
        assert listings[1]["quantity"] == 2

    def test_captures_section_and_row_when_present(self):
        payload = [{"price": 500, "quantity": 2, "sectionName": "200", "row": "F"}]

        listings = common.extract_listings(payload)

        assert listings[0]["section"] == "200"
        assert listings[0]["row"] == "F"

    def test_ignores_dicts_missing_price_or_quantity(self):
        payload = {"price": 500, "somethingElse": "no quantity here"}

        assert common.extract_listings(payload) == []

    def test_plain_numeric_price_field(self):
        payload = {"total": 350, "qty": 2}

        listings = common.extract_listings(payload)

        assert listings[0]["price_per_ticket"] == 350.0


class TestExtractEmbeddedJsonBlobs:
    def test_finds_next_data_script_tag(self):
        html = (
            '<script id="__NEXT_DATA__" type="application/json">'
            '{"listings": [{"price": 599, "quantity": 2}]}'
            "</script>"
        )

        blobs = common.extract_embedded_json_blobs(html)

        assert len(blobs) == 1
        assert blobs[0]["listings"][0]["price"] == 599

    def test_finds_window_initial_state_assignment(self):
        html = 'window.__INITIAL_STATE__ = {"listings": [{"price": 480, "quantity": 2}]};'

        blobs = common.extract_embedded_json_blobs(html)

        assert len(blobs) == 1
        assert blobs[0]["listings"][0]["price"] == 480

    def test_ignores_unparseable_blobs(self):
        html = '<script id="__NEXT_DATA__">{not valid json</script>'

        assert common.extract_embedded_json_blobs(html) == []

    def test_no_matches_returns_empty_list(self):
        assert common.extract_embedded_json_blobs("<html><body>hi</body></html>") == []

    def test_end_to_end_picks_real_pair_price_over_single_ticket(self):
        html = (
            '<script id="__NEXT_DATA__" type="application/json">'
            '{"listings": [{"price": 599, "quantity": 2}, {"price": 390, "quantity": 1}]}'
            "</script>"
        )

        blobs = common.extract_embedded_json_blobs(html)
        listings = []
        for blob in blobs:
            listings.extend(common.extract_listings(blob))
        best = common.lowest_pair_price(listings)

        assert best["price_per_ticket"] == 599.0


class TestFindScriptIds:
    def test_finds_distinct_script_ids(self):
        html = (
            '<script id="__NUXT_DATA__">{...}</script>'
            '<script id="gtm-script">console.log(1)</script>'
        )

        assert common.find_script_ids(html) == ["__NUXT_DATA__", "gtm-script"]

    def test_no_script_tags_returns_empty_list(self):
        assert common.find_script_ids("<html><body>hi</body></html>") == []


class TestCheckPriceDiagnostic:
    def test_fallback_surfaces_breadcrumb_when_nothing_structural_found(self):
        # simulates: page loaded fine (not blocked), no network JSON
        # matched, no known embedded-JSON pattern matched - the diagnostic
        # should carry the script-id/URL breadcrumb from fetch_with_capture
        # rather than just "no price found in fallback text"
        fake_result = common.FetchResult(
            "ok",
            http_status=200,
            captured=[],
            text="Sec 100 $489 each",
            diagnostic="no network JSON matched; script tag ids on page: ['__NUXT_DATA__']",
        )
        with patch("scrapers.common.fetch_with_capture", return_value=fake_result):
            result = common.check_price("https://example.com", re.compile("x"))

        assert result["status"] == "fallback"
        assert "__NUXT_DATA__" in result["diagnostic"]

    def test_fallback_with_no_price_still_reports_something(self):
        fake_result = common.FetchResult(
            "ok", http_status=200, captured=[], text="no prices here", diagnostic=""
        )
        with patch("scrapers.common.fetch_with_capture", return_value=fake_result):
            result = common.check_price("https://example.com", re.compile("x"))

        assert result["status"] == "error"
        assert result["diagnostic"] == "no price found in fallback text"


class TestLowestPairPrice:
    def test_ignores_single_seat_listings(self):
        listings = [
            {"price_per_ticket": 712.5, "quantity": 1},
            {"price_per_ticket": 489.0, "quantity": 2},
            {"price_per_ticket": 8950.0, "quantity": 4},
        ]

        best = common.lowest_pair_price(listings)

        assert best["price_per_ticket"] == 489.0

    def test_returns_none_when_no_pairs_available(self):
        listings = [{"price_per_ticket": 200.0, "quantity": 1}]

        assert common.lowest_pair_price(listings) is None

    def test_empty_listings_returns_none(self):
        assert common.lowest_pair_price([]) is None
