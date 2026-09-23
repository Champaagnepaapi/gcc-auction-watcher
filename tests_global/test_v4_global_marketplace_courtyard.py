from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from v4_global_marketplace_courtyard import (
    asset_urls_from_values,
    parse_courtyard_asset_page,
)
from v4_global_market_core import FIXED_ASK
from v4_global_marketplace_scan import scan_courtyard_inventory


NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
ASSET = "https://marketplace.courtyard.io/asset/" + "a" * 64


def _script(**overrides):
    row = {
        "listingStatus": "ACTIVE",
        "listingPriceUsd": 80.0,
        "card": {
            "game": "Pokemon",
            "cardName": "Mew VMAX",
            "setName": "Fusion Strike",
            "cardNumber": "269/264",
            "language": "English",
            "grader": "PSA",
            "grade": "10",
        },
    }
    row.update(overrides)
    return json.dumps({"listing": row})


class CourtyardMarketplaceTests(unittest.TestCase):
    def test_asset_url_discovery_strips_tracking_query_and_deduplicates(self):
        values = [ASSET + "?fmvUsd=999&source=marketplace", ASSET, "https://example.com/no"]
        self.assertEqual(asset_urls_from_values(values), [ASSET])

    def test_exact_active_listing_is_fixed_ask_but_all_in_remains_unproven(self):
        listing = parse_courtyard_asset_page(
            source_url=ASSET,
            body="Vaulted and insured\nBuy Now\n$80",
            script_texts=[_script()],
            observed_at=NOW,
        )
        self.assertIsNotNone(listing)
        assert listing is not None
        self.assertEqual(listing.market, "courtyard")
        self.assertEqual(listing.evidence_type, FIXED_ASK)
        self.assertEqual(listing.price, 80.0)
        self.assertEqual(listing.currency, "USD")
        self.assertIsNone(listing.buyer_fee_rate)
        self.assertIsNone(listing.all_in_eur({"USD": 1.2}))
        self.assertEqual(
            listing.identity.strict_key,
            "mew vmax|fusion strike|269/264|en|PSA|10|||",
        )

    def test_not_listed_asset_never_becomes_offer_even_if_query_contains_fmv(self):
        listing = parse_courtyard_asset_page(
            source_url=ASSET + "?fmvUsd=179.7&percentOff=-20",
            body="Not listed\nMake an offer\nCourtyard Pricing\nMarket Value: $179.70",
            script_texts=[_script(listingStatus="INACTIVE")],
            observed_at=NOW,
        )
        self.assertIsNone(listing)

    def test_courtyard_fmv_is_never_used_as_listing_price(self):
        script = json.dumps(
            {
                "asset": {
                    "fmvUsd": 179.7,
                    "card": {
                        "game": "Pokemon",
                        "cardName": "Mew VMAX",
                        "setName": "Fusion Strike",
                        "cardNumber": "269/264",
                        "language": "English",
                        "grader": "PSA",
                        "grade": "10",
                    },
                }
            }
        )
        listing = parse_courtyard_asset_page(
            source_url=ASSET,
            body="Courtyard Pricing\nMarket Value: $179.70\nMake an offer",
            script_texts=[script],
            observed_at=NOW,
        )
        self.assertIsNone(listing)

    def test_missing_language_or_number_fails_closed(self):
        missing_language = json.dumps(
            {
                "listing": {
                    "listingStatus": "ACTIVE",
                    "listingPriceUsd": 80,
                    "card": {
                        "game": "Pokemon",
                        "cardName": "Mew VMAX",
                        "setName": "Fusion Strike",
                        "cardNumber": "269/264",
                        "grader": "PSA",
                        "grade": "10",
                    },
                }
            }
        )
        missing_number = json.dumps(
            {
                "listing": {
                    "listingStatus": "ACTIVE",
                    "listingPriceUsd": 80,
                    "card": {
                        "game": "Pokemon",
                        "cardName": "Mew VMAX",
                        "setName": "Fusion Strike",
                        "language": "English",
                        "grader": "PSA",
                        "grade": "10",
                    },
                }
            }
        )
        for script in (missing_language, missing_number):
            with self.subTest(script=script):
                self.assertIsNone(
                    parse_courtyard_asset_page(
                        source_url=ASSET,
                        body="Buy Now\n$80",
                        script_texts=[script],
                        observed_at=NOW,
                    )
                )

    def test_conflicting_exact_identity_or_price_fails_closed(self):
        other = json.loads(_script())
        other["listing"]["listingPriceUsd"] = 81
        self.assertIsNone(
            parse_courtyard_asset_page(
                source_url=ASSET,
                body="Buy Now\n$80",
                script_texts=[_script(), json.dumps(other)],
                observed_at=NOW,
            )
        )


    def test_public_scanner_is_bounded_and_never_claims_pagination_complete(self):
        class Response:
            status = 200

        class Locator:
            def __init__(self, kind):
                self.kind = kind

            def inner_text(self, timeout=None):
                return "Vaulted and insured\\nBuy Now\\n$80"

            def all_text_contents(self):
                return [_script()]

        class Page:
            def __init__(self):
                self.current = ""

            def goto(self, url, **kwargs):
                self.current = url
                return Response()

            def wait_for_timeout(self, _milliseconds):
                return None

            def evaluate(self, expression):
                if "querySelectorAll" in expression:
                    return [ASSET]
                return None

            def content(self):
                return ""

            def locator(self, selector):
                return Locator("body" if selector == "body" else "script")

        rows, status = scan_courtyard_inventory(
            Page(), observed_at=NOW, max_detail_pages=1, scroll_rounds=1
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(status.market, "courtyard")
        self.assertEqual(status.status, "OK")
        self.assertEqual(status.candidates, 1)
        self.assertEqual(status.exact, 1)
        self.assertFalse(status.complete)
        self.assertIn("FMV ignored", status.detail)

    def test_public_scanner_does_not_bypass_http_block(self):
        class Response:
            status = 403

        class Page:
            def goto(self, url, **kwargs):
                return Response()

            def wait_for_timeout(self, _milliseconds):
                return None

        rows, status = scan_courtyard_inventory(Page(), observed_at=NOW)
        self.assertEqual(rows, [])
        self.assertEqual(status.status, "UNAVAILABLE")
        self.assertEqual(status.detail, "HTTP_403")
        self.assertFalse(status.complete)



    def test_nft_trait_metadata_with_accented_pokemon_category_is_exact(self):
        traits = [
            {"trait_type": "Grader", "value": "PSA"},
            {"trait_type": "Grade", "value": "10 GEM MINT"},
            {"trait_type": "Category", "value": "Pokémon"},
            {"trait_type": "Set", "value": "Pokémon S Promo"},
            {"trait_type": "Title/Subject", "value": "Pikachu"},
            {"trait_type": "Language", "value": "Japanese"},
            {"trait_type": "Card Number", "value": "272"},
            {"trait_type": "property", "value": "Holo"},
            {"trait_type": "property", "value": "Pokemon Go Card File Set"},
        ]
        script = json.dumps(
            {
                "listing": {
                    "listingStatus": "ACTIVE",
                    "listingPriceUsd": 125,
                    "asset": {"metadata": {"attributes": traits}},
                }
            }
        )
        listing = parse_courtyard_asset_page(
            source_url=ASSET,
            body="Vaulted and insured\nBuy Now\n$125",
            script_texts=[script],
            observed_at=NOW,
        )
        self.assertIsNotNone(listing)
        assert listing is not None
        self.assertEqual(listing.identity.name, "Pikachu")
        self.assertEqual(listing.identity.set_name, "Pokémon S Promo")
        self.assertEqual(listing.identity.number, "272")
        self.assertEqual(listing.identity.language, "ja")
        self.assertEqual(listing.identity.grader, "PSA")
        self.assertEqual(listing.identity.grade, "10")
        self.assertEqual(listing.identity.finish, "Holo")
        self.assertEqual(listing.identity.variant, "Pokemon Go Card File Set")

    def test_nft_trait_metadata_requires_explicit_pokemon_category(self):
        traits = [
            {"trait_type": "Grader", "value": "PSA"},
            {"trait_type": "Grade", "value": "10 GEM MINT"},
            {"trait_type": "Category", "value": "Baseball"},
            {"trait_type": "Set", "value": "Topps"},
            {"trait_type": "Title/Subject", "value": "Pikachu"},
            {"trait_type": "Language", "value": "English"},
            {"trait_type": "Card Number", "value": "25"},
        ]
        script = json.dumps(
            {
                "listing": {
                    "listingStatus": "ACTIVE",
                    "listingPriceUsd": 125,
                    "asset": {"metadata": {"attributes": traits}},
                }
            }
        )
        self.assertIsNone(
            parse_courtyard_asset_page(
                source_url=ASSET,
                body="Buy Now\n$125",
                script_texts=[script],
                observed_at=NOW,
            )
        )


    def test_dom_fallback_requires_explicit_pokemon_category(self):
        body = """Name
Pikachu
Set
Pokémon S Promo
Card Number
272
Language
Japanese
Grader
PSA
Grade
10
Buy Now
$125"""
        self.assertIsNone(
            parse_courtyard_asset_page(
                source_url=ASSET,
                body=body,
                script_texts=[],
                observed_at=NOW,
            )
        )

        proven = "Category\nPokémon\n" + body
        listing = parse_courtyard_asset_page(
            source_url=ASSET,
            body=proven,
            script_texts=[],
            observed_at=NOW,
        )
        self.assertIsNotNone(listing)


if __name__ == "__main__":
    unittest.main()
