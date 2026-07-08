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

    def test_does_not_misinterpret_seatmap_heatmap_data_as_a_listing(self):
        # regression test: this shape (single-letter "l"/"h" price-range
        # fields, empty seller/listing/product ids, geometric rendering
        # fields) is real Vivid Seats data but is seat-map heatmap/
        # visualization data, not an individual bookable listing - an
        # earlier version of extract_listings wrongly special-cased "l"
        # as price and "q" as quantity here, which silently returned a
        # fabricated price at fake "high" confidence
        heatmap_zone = {
            "productionId": 6642335, "i": "5001", "g": "394260", "a": "1",
            "h": "798.00", "l": "621.00", "q": "3", "n": "Field A1",
            "si": "", "li": "", "pi": "", "laip": "837.35", "mbi": "",
            "s3d": "", "p3d": "", "rd": "null", "ss": 9.5, "ang": 56.01,
            "dst": 55.69, "rx": 45.32, "ry": 30.56, "localPrices": None,
        }

        assert common.extract_listings(heatmap_zone) == []

    def test_parses_real_vividseats_ticket_schema(self):
        # the actual payload["tickets"] item shape captured from the live
        # site: "q" is quantity, "s" is section, "r" is row, "i" is a real
        # alphanumeric listing id (unlike the heatmap/groups shape's empty
        # seller/listing/product id fields above). Price uses "aip" (all-in,
        # fees included) not "p" (base price) - see next test for why.
        real_ticket = {
            "s": "Promenade Reserved 527", "r": "15", "q": "1", "p": "294.50",
            "i": "VB16030960293", "d": "527", "aip": "397.46",
            "stp": "Ticketmaster Transfer", "faceValue": "0.00", "di": False,
        }

        listings = common.extract_listings(real_ticket)

        assert listings == [
            {
                "price_per_ticket": 397.46, "quantity": 1,
                "section": "Promenade Reserved 527", "row": "15",
            }
        ]

    def test_prefers_aip_all_in_price_over_base_price(self):
        # regression test: caught via a live cross-check. Our alert for
        # section "Promenade Reserved 528" row "9" said $444 (the "p"
        # field), but the live site's *same listing* (matched by section
        # + row) showed $599 labeled "Fees Incl.". $599/$444 = 1.349,
        # matching the aip/p ratio in the original sample data
        # (397.46/294.50 = 1.350) almost exactly - "p" is pre-fee, "aip"
        # is the real displayed/payable price.
        payload = {"s": "Promenade Reserved 528", "r": "9", "q": "2", "p": "444", "aip": "599"}

        listings = common.extract_listings(payload)

        assert listings[0]["price_per_ticket"] == 599.0

    def test_falls_back_to_base_price_when_aip_missing(self):
        payload = {"s": "A", "r": "1", "q": "2", "p": "500"}

        listings = common.extract_listings(payload)

        assert listings[0]["price_per_ticket"] == 500.0

    def test_falls_back_to_base_price_when_aip_unparseable(self):
        payload = {"s": "A", "r": "1", "q": "2", "p": "500", "aip": "call for price"}

        listings = common.extract_listings(payload)

        assert listings[0]["price_per_ticket"] == 500.0

    def test_vividseats_groups_shape_is_still_ignored_not_tickets(self):
        # "groups" (section price-range summaries) superficially looks
        # like the same "l"/"h"/"q" shape as the heatmap data above and
        # must NOT be picked up as a real listing - its "q" means "count
        # of listings in this section", not a purchasable quantity, and it
        # has no row field at all
        real_group = {
            "productionId": 6642335, "i": "394259", "n": "Front Porch",
            "h": "3421.00", "l": "1262.00", "q": "22", "g": "1",
            "localPrices": None,
        }

        assert common.extract_listings(real_group) == []

    def test_vividseats_ticket_schema_ignores_unparseable_values(self):
        payload = {"s": "A", "r": "1", "q": "1", "p": "not-a-number"}

        assert common.extract_listings(payload) == []

    def test_picks_real_pair_price_from_mixed_ticket_array(self):
        # end-to-end: a realistic array mixing a 1-ticket listing (cheaper)
        # with a real 2-together listing - must pick the latter, not just
        # the globally cheapest single ticket
        tickets = [
            {"s": "Promenade 527", "r": "15", "q": "1", "p": "294.50", "i": "VB1"},
            {"s": "Promenade 527", "r": "11", "q": "2", "p": "599.00", "i": "VB2"},
            {"s": "Field A1", "r": "3", "q": "4", "p": "621.00", "i": "VB3"},
        ]

        listings = common.extract_listings(tickets)
        best = common.lowest_pair_price(listings)

        assert best["price_per_ticket"] == 599.0
        assert best["row"] == "11"


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

    def test_fallback_dumps_sample_payload_when_captured_but_unmatched(self):
        # this is the real scenario hit in production: JSON was captured
        # (network + embedded) but extract_listings' generic price/quantity
        # key-matching didn't find anything usable in it - the diagnostic
        # should show the real payload shape instead of a generic message
        fake_result = common.FetchResult(
            "ok",
            http_status=200,
            captured=[{"ticketGroups": [{"cost": 398, "seatCount": 1}]}],
            text="Sec 100 $398 each",
            diagnostic="",
        )
        with patch("scrapers.common.fetch_with_capture", return_value=fake_result):
            result = common.check_price("https://example.com", re.compile("x"))

        assert result["status"] == "fallback"
        assert "captured 1 JSON payload" in result["diagnostic"]
        assert "ticketGroups" in result["diagnostic"]


class TestSummarizeCapturedPayloads:
    def test_finds_nested_list_not_just_top_level(self):
        # reproduces the real production case: the first captured payload
        # is empty pagination metadata, and the real data is nested one
        # level deep in a later payload, not at the top level
        captured = [
            {"meta": {"pagination": {"page": None}}, "listings": []},
            {"data": {"ticketGroups": [{"retailPrice": 599, "availableTicketCount": 2}]}},
        ]

        summary = common.summarize_captured_payloads(captured)

        assert "payload[0]" in summary
        assert "payload[1]" in summary
        assert "retailPrice" in summary
        assert "599" in summary

    def test_empty_captured_list_returns_empty_string(self):
        assert common.summarize_captured_payloads([]) == ""

    def test_handles_non_dict_non_list_payloads(self):
        summary = common.summarize_captured_payloads(["a string", 42, None])
        assert "payload[0]" in summary


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
