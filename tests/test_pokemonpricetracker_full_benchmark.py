from __future__ import annotations

import unittest

from v5.pokemonpricetracker_adapter import CanonicalPptIdentity
from v5.pokemonpricetracker_full_benchmark import (
    CREDIT_CAP,
    HTTP_CALL_CAP,
    PANEL,
    Runtime,
    STOP_DAILY_REMAINING,
    _ebay_summary,
    _raw_history_summary,
    search_attempts,
)


class PokemonPriceTrackerFullBenchmarkTests(unittest.TestCase):
    def test_panel_is_broad_but_bounded(self) -> None:
        self.assertGreaterEqual(len(PANEL), 15)
        self.assertLessEqual(len(PANEL), 20)
        self.assertLessEqual(HTTP_CALL_CAP, 50)
        self.assertLessEqual(CREDIT_CAP, 500)
        self.assertGreaterEqual(STOP_DAILY_REMAINING, 15000)

    def test_lugia_search_is_set_constrained_first(self) -> None:
        card = CanonicalPptIdentity("swsh12-186", "Lugia V", "Silver Tempest", "186", "en")
        first = search_attempts(card)[0]
        self.assertEqual(first["search"], "Lugia V")
        self.assertEqual(first["setName"], "Silver Tempest")
        self.assertEqual(first["limit"], 5)

    def test_runtime_fails_closed_without_credit_header(self) -> None:
        runtime = Runtime()
        runtime.record({"X-Ratelimit-Daily-Remaining": "19000"})
        self.assertTrue(runtime.blocked)
        self.assertIn("CREDIT_HEADER_REQUIRED", runtime.errors)

    def test_runtime_fails_closed_without_daily_remaining(self) -> None:
        runtime = Runtime()
        runtime.record({"X-Api-Calls-Consumed": "4"})
        self.assertTrue(runtime.blocked)
        self.assertIn("DAILY_REMAINING_HEADER_REQUIRED", runtime.errors)

    def test_runtime_tracks_credits_and_remaining(self) -> None:
        runtime = Runtime()
        runtime.record({
            "X-Api-Calls-Consumed": "4",
            "X-Ratelimit-Daily-Remaining": "19000",
        })
        self.assertEqual(runtime.http_calls, 1)
        self.assertEqual(runtime.credits, 4)
        self.assertEqual(runtime.daily_remaining, 19000)
        self.assertFalse(runtime.blocked)

    def test_raw_history_summary_counts_condition_history(self) -> None:
        row = {
            "priceHistory": {
                "totalDataPoints": 2,
                "conditions": {
                    "Near Mint": {"history": [
                        {"date": "2026-02-01", "market": 10},
                        {"date": "2026-08-01", "market": 20},
                    ]}
                },
                "variants": {},
            }
        }
        summary = _raw_history_summary(row)
        self.assertEqual(summary["conditions"]["Near Mint"]["points"], 2)
        self.assertEqual(summary["conditions"]["Near Mint"]["oldest"], "2026-02-01")
        self.assertEqual(summary["conditions"]["Near Mint"]["newest"], "2026-08-01")

    def test_ebay_summary_keeps_aggregate_semantics(self) -> None:
        row = {
            "ebay": {
                "totalSales": 3,
                "salesByGrade": {
                    "psa10": {
                        "count": 3,
                        "averagePrice": 100,
                        "medianPrice": 101,
                        "smartMarketPrice": {"price": 102, "confidence": "high"},
                    }
                },
                "priceHistory": {
                    "psa10": {
                        "2026-08-01": {"count": 2, "average": 99, "totalValue": 198},
                        "2026-08-02": {"count": 1, "average": 102, "totalValue": 102},
                    }
                },
            }
        }
        summary = _ebay_summary(row)
        self.assertEqual(summary["totalSales"], 3)
        self.assertEqual(summary["gradeBuckets"], 1)
        self.assertEqual(summary["dailyGradeHistory"]["psa10"]["days"], 2)
        self.assertEqual(summary["dailyGradeHistory"]["psa10"]["sale_count_in_daily_history"], 3)
        self.assertIn("NOT_ITEM_LEVEL", summary["semantics"])


if __name__ == "__main__":
    unittest.main()
