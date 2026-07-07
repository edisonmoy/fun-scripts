from scrapers import common


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
