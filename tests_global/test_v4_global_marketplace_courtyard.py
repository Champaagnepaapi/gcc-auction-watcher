from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from v4_global_marketplace_courtyard import (
    asset_urls_from_values,
    parse_courtyard_asset_page,
)
from v4_global_market_core import FIXED_ASK


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


if __name__ == "__main__":
    unittest.main()
