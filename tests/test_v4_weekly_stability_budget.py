from __future__ import annotations

import unittest
from unittest.mock import patch

import watcher
import v4_private_auction_coverage as coverage


class WeeklyStabilityBudgetTests(unittest.TestCase):
    def lot(self, index: int) -> watcher.Lot:
        return watcher.Lot(
            url=f"https://gradedcardcenter.com/item/{index:03d}",
            title=f"PSA 9 Pikachu {index:03d}",
            current_price=50.0,
            source_type="auction",
            minutes_to_end=30,
        )

    def snapshot(self, size: int) -> list[watcher.Lot]:
        return [self.lot(index) for index in range(size)]

    def test_budget_matches_live_drift_and_accepts_only_after_zero_growth_pass(self):
        self.assertEqual(coverage.WEEKLY_STABILITY_MAX_PASSES, 5)
        snapshots = [
            self.snapshot(291),
            self.snapshot(312),  # live incident: +21
            self.snapshot(314),  # live incident: +2
            self.snapshot(314),  # first proof of stable union
        ]
        calls = 0

        def collect_sale(_page, _sale, _source_type, _diagnostics):
            nonlocal calls
            result = snapshots[calls]
            calls += 1
            return result

        with patch.object(
            coverage.item_discovery,
            "_ORIGINAL_COLLECT_LOTS_FROM_LISTING",
            side_effect=collect_sale,
        ):
            lots, stable = coverage._collect_weekly_sale_stable(
                object(),
                "https://gradedcardcenter.com/filtres/auction/weekly/live-incident",
                watcher.RunDiagnostics(),
            )

        self.assertTrue(stable)
        self.assertEqual(calls, 4)
        self.assertEqual(len(lots), 314)

    def test_growth_through_fifth_pass_still_fails_closed(self):
        snapshots = [
            self.snapshot(10),
            self.snapshot(11),
            self.snapshot(12),
            self.snapshot(13),
            self.snapshot(14),
        ]
        calls = 0

        def collect_sale(_page, _sale, _source_type, _diagnostics):
            nonlocal calls
            result = snapshots[calls]
            calls += 1
            return result

        with patch.object(
            coverage.item_discovery,
            "_ORIGINAL_COLLECT_LOTS_FROM_LISTING",
            side_effect=collect_sale,
        ):
            lots, stable = coverage._collect_weekly_sale_stable(
                object(),
                "https://gradedcardcenter.com/filtres/auction/weekly/still-growing",
                watcher.RunDiagnostics(),
            )

        self.assertFalse(stable)
        self.assertEqual(calls, 5)
        self.assertEqual(len(lots), 14)


if __name__ == "__main__":
    unittest.main()
