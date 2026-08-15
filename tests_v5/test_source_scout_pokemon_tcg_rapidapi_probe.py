from __future__ import annotations

import unittest

from v5 import source_scout_pokemon_tcg_rapidapi_probe as target


class PokemonTcgRapidApiProbeTests(unittest.TestCase):
    def test_budget_is_tiny_and_safe(self) -> None:
        self.assertEqual(target.CALL_CAP, 12)
        self.assertGreaterEqual(target.STOP_REMAINING, 80)
        self.assertEqual(len(target.PANEL), 5)
        self.assertEqual(len(target.HISTORY_SENTINELS), 2)

    def test_quota_header_parsing(self) -> None:
        self.assertEqual(target.quota_remaining({"x-ratelimit-requests-remaining": "99"}), 99)
        self.assertEqual(target.quota_remaining({"X-RateLimit-Rapid-Free-Plans-Requests-Remaining": "88.0"}), 88)
        self.assertIsNone(target.quota_remaining({"content-type": "application/json"}))

    def test_offer_comparison_tracks_domain_currency_and_overlap(self) -> None:
        old = {
            "123": {
                "ebay_item_id": "123",
                "price": 100,
                "currency": "GBP",
                "url": "https://www.ebay.co.uk/itm/123",
            }
        }
        new = [
            {
                "ebay_item_id": "123",
                "price": 130,
                "currency": "USD",
                "url": "https://www.ebay.com/itm/123",
            }
        ]
        result = target.compare_offers(new, old)
        self.assertEqual(result["cmapi_overlap"], 1)
        self.assertEqual(result["currencies"], {"USD": 1})
        self.assertEqual(result["domains"], {"www.ebay.com": 1})
        example = result["overlap_examples"][0]
        self.assertEqual(example["new_currency"], "USD")
        self.assertEqual(example["cmapi_currency"], "GBP")


if __name__ == "__main__":
    unittest.main()
