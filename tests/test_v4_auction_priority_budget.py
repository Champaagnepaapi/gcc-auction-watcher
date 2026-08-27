from __future__ import annotations

import os
from pathlib import Path
import unittest

import watcher
import v4_auction_priority_budget as priority


def lot(idx: int, minutes: int, price: float = 50.0, source_type: str = "auction") -> watcher.Lot:
    return watcher.Lot(
        url=f"https://gradedcardcenter.com/item/{idx:032d}",
        title=f"Card {idx}",
        current_price=price,
        source_type=source_type,
        minutes_to_end=minutes,
    )


class AuctionPriorityBudgetTests(unittest.TestCase):
    def setUp(self):
        self.old_cap = watcher.MAX_AUCTION_CANDIDATES
        self.old_register = watcher.EconomicCoverageAudit.register_candidates
        self.old_installed = priority._INSTALLED
        self.old_env = os.environ.get(priority.CAP_ENV)
        priority._INSTALLED = False

    def tearDown(self):
        watcher.MAX_AUCTION_CANDIDATES = self.old_cap
        watcher.EconomicCoverageAudit.register_candidates = self.old_register
        priority._INSTALLED = self.old_installed
        if self.old_env is None:
            os.environ.pop(priority.CAP_ENV, None)
        else:
            os.environ[priority.CAP_ENV] = self.old_env

    def test_default_cap_covers_observed_300_plus_wave(self):
        os.environ.pop(priority.CAP_ENV, None)
        priority.install_v4_auction_priority_budget()
        candidates = [lot(i, 45) for i in range(330)]
        audit = watcher.EconomicCoverageAudit("AUCTIONS")
        audit.register_candidates(
            candidates,
            discovered_listings=330,
            valuation_cap=watcher.MAX_AUCTION_CANDIDATES,
        )
        selected = candidates[: watcher.MAX_AUCTION_CANDIDATES]
        self.assertEqual(watcher.MAX_AUCTION_CANDIDATES, 360)
        self.assertEqual(len(selected), 330)

    def test_priority_is_absolute_le5_then_le12_then_rest_le60(self):
        os.environ[priority.CAP_ENV] = "360"
        priority.install_v4_auction_priority_budget()
        candidates = []
        candidates.extend(lot(i, 45) for i in range(350))
        candidates.extend(lot(1000 + i, 10) for i in range(30))
        candidates.extend(lot(2000 + i, 4) for i in range(20))
        audit = watcher.EconomicCoverageAudit("AUCTIONS")
        audit.register_candidates(
            candidates,
            discovered_listings=len(candidates),
            valuation_cap=watcher.MAX_AUCTION_CANDIDATES,
        )
        selected = candidates[: watcher.MAX_AUCTION_CANDIDATES]
        skipped = candidates[watcher.MAX_AUCTION_CANDIDATES :]

        self.assertEqual(len(selected), 360)
        self.assertEqual(sum(x.minutes_to_end <= 5 for x in selected), 20)
        self.assertEqual(sum(x.minutes_to_end <= 12 for x in selected), 50)
        self.assertTrue(all(x.minutes_to_end > 12 for x in skipped))
        self.assertEqual([priority.auction_priority_bucket(x) for x in selected[:20]], [0] * 20)
        self.assertEqual([priority.auction_priority_bucket(x) for x in selected[20:50]], [1] * 30)

    def test_cap_override_cannot_drop_below_historical_120_or_exceed_600(self):
        os.environ[priority.CAP_ENV] = "40"
        self.assertEqual(priority.configured_auction_evaluation_cap(), 120)
        os.environ[priority.CAP_ENV] = "9000"
        self.assertEqual(priority.configured_auction_evaluation_cap(), 600)
        os.environ[priority.CAP_ENV] = "not-an-int"
        self.assertEqual(priority.configured_auction_evaluation_cap(), 360)

    def test_fixed_candidate_order_is_not_changed(self):
        priority.install_v4_auction_priority_budget()
        candidates = [
            lot(1, 50, source_type="fixed"),
            lot(2, 3, source_type="fixed"),
            lot(3, 10, source_type="fixed"),
        ]
        before = [x.url for x in candidates]
        audit = watcher.EconomicCoverageAudit("FIXED PRICE")
        audit.register_candidates(candidates, discovered_listings=3, valuation_cap=120)
        self.assertEqual([x.url for x in candidates], before)

    def test_production_wiring_uses_priority_budget_installer(self):
        source = Path("run_watcher_multimarket.py").read_text(encoding="utf-8")
        self.assertIn("install_v4_auction_priority_budget", source)
        self.assertIn("install_v4_auction_priority_budget()", source)

    def test_workflow_pins_expanded_cap_explicitly(self):
        workflow = Path(".github/workflows/watcher.yml").read_text(encoding="utf-8")
        self.assertIn('V4_AUCTION_EVALUATION_CAP: "360"', workflow)


if __name__ == "__main__":
    unittest.main()
