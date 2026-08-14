from __future__ import annotations

import unittest

from v5 import source_scout_cmapi_v3_entrypoint as cmapi


class CmapiV3SafetyTests(unittest.TestCase):
    def test_paid_overage_guard_is_conservative(self) -> None:
        self.assertLessEqual(cmapi.MAX_CMAPI_CALLS, 25)
        self.assertGreaterEqual(cmapi.STOP_IF_REMAINING_AT_OR_BELOW, 10)
        self.assertLess(cmapi.MAX_CMAPI_CALLS, 100)
        self.assertLessEqual(cmapi.TOTAL_CAP_BYTES, 20_000_000)


class CmapiV3ParserTests(unittest.TestCase):
    def test_history_summary_preserves_language_price_fields(self) -> None:
        payload = {
            "data": {
                "2026-08-14": {"cm_low": 12.5, "cm_low_fr": 11.8, "tcg_player_market": 14.2},
                "2026-08-13": {"cm_low": 12.0, "cm_low_fr": 11.5, "tcg_player_market": 14.0},
            }
        }
        summary = cmapi._history_summary(payload)
        self.assertEqual(summary["point_count"], 2)
        self.assertEqual(summary["newest_date"], "2026-08-14")
        self.assertEqual(summary["oldest_date"], "2026-08-13")
        self.assertEqual(summary["latest_points"][0]["cm_low_fr"], 11.8)

    def test_ebay_summary_keeps_psa10_median_and_sample(self) -> None:
        payload = {
            "data": [
                {"company": "PSA", "grade": "10", "median_price": 310.0, "sample_size": 5},
                {"company": "BGS", "grade": "9.5", "median_price": 220.0, "sample_size": 3},
            ]
        }
        summary = cmapi._ebay_graded_summary(payload)
        self.assertEqual(summary["grade_rows"], 2)
        self.assertEqual(summary["total_sample_size"], 8)
        self.assertEqual(len(summary["psa10"]), 1)
        self.assertEqual(summary["psa10"][0]["median_price"], 310.0)
        self.assertEqual(summary["psa10"][0]["sample_size"], 5)

    def test_sold_offer_summary_keeps_final_sale_fields(self) -> None:
        payload = {
            "data": [
                {
                    "ebay_item_id": "123",
                    "title": "Example PSA 10",
                    "price": 99.5,
                    "currency": "USD",
                    "company": "PSA",
                    "grade": "10",
                    "ended_at": "2026-08-13T12:00:00+00:00",
                    "image_url": "https://example.invalid/image.jpg",
                }
            ]
        }
        summary = cmapi._offers_summary(payload)
        self.assertEqual(summary["offer_count"], 1)
        offer = summary["offers"][0]
        self.assertEqual(offer["ebay_item_id"], "123")
        self.assertEqual(offer["price"], 99.5)
        self.assertEqual(offer["company"], "PSA")
        self.assertEqual(offer["grade"], "10")
        self.assertEqual(offer["ended_at"], "2026-08-13T12:00:00+00:00")
        self.assertNotIn("image_url", offer)


if __name__ == "__main__":
    unittest.main()
