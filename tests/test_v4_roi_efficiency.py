from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import watcher
import v4_roi_efficiency as roi


class RoiEfficiencyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)

    def candidate(self, recent=(120, 130), baseline=(80, 90), price=70, age_days=30):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/roi-test",
            title="PSA 10 Pikachu",
            current_price=price,
            source_type="fixed",
            grader="PSA",
            grade="10",
            card_number="#25/102",
            card_set="Base Set",
            language="French",
        )
        setattr(lot, "gcc_created_at", self.now - timedelta(days=age_days))
        sales = []
        for idx, value in enumerate(recent):
            sales.append(
                watcher.ComparableSale(
                    price=float(value),
                    source="gcc",
                    grader="PSA",
                    grade=10.0,
                    sold_at=self.now - timedelta(days=10 + idx * 10),
                    exact_card=True,
                )
            )
        for idx, value in enumerate(baseline):
            sales.append(
                watcher.ComparableSale(
                    price=float(value),
                    source="gcc",
                    grader="PSA",
                    grade=10.0,
                    sold_at=self.now - timedelta(days=120 + idx * 30),
                    exact_card=True,
                )
            )
        return SimpleNamespace(lot=lot, gcc=SimpleNamespace(sales=sales))

    def test_created_at_parser_requires_valid_timestamp(self):
        parsed = roi.parse_gcc_created_at("2026-08-01T12:30:00Z")
        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertIsNone(roi.parse_gcc_created_at("not-a-date"))
        self.assertIsNone(roi.parse_gcc_created_at(""))

    def test_stale_listing_plus_exact_sold_momentum_is_detected(self):
        signal = roi.market_momentum_signal(self.candidate(), self.now)
        self.assertIsNotNone(signal)
        self.assertTrue(signal.stale_listing)
        self.assertTrue(signal.actionable_edge)
        self.assertGreater(signal.momentum_pct, 30)
        self.assertGreater(signal.price_gap_pct, 30)

    def test_sparse_windows_fail_closed(self):
        candidate = self.candidate(recent=(120,), baseline=(80, 90))
        self.assertIsNone(roi.market_momentum_signal(candidate, self.now))

    def test_wrong_grader_and_wrong_grade_do_not_enter_momentum(self):
        candidate = self.candidate(recent=(), baseline=())
        candidate.gcc.sales = [
            watcher.ComparableSale(
                price=200,
                source="gcc",
                grader="PCA",
                grade=10.0,
                sold_at=self.now - timedelta(days=10),
                exact_card=True,
            ),
            watcher.ComparableSale(
                price=210,
                source="gcc",
                grader="PSA",
                grade=9.0,
                sold_at=self.now - timedelta(days=20),
                exact_card=True,
            ),
            watcher.ComparableSale(
                price=100,
                source="gcc",
                grader="PSA",
                grade=10.0,
                sold_at=self.now - timedelta(days=120),
                exact_card=True,
            ),
            watcher.ComparableSale(
                price=105,
                source="gcc",
                grader="PSA",
                grade=10.0,
                sold_at=self.now - timedelta(days=150),
                exact_card=True,
            ),
        ]
        self.assertIsNone(roi.market_momentum_signal(candidate, self.now))

    def test_recent_drop_is_not_positive_momentum_edge(self):
        signal = roi.market_momentum_signal(
            self.candidate(recent=(70, 75), baseline=(100, 110), price=60), self.now
        )
        self.assertIsNotNone(signal)
        self.assertLess(signal.momentum_pct, 0)
        self.assertFalse(signal.actionable_edge)

    def test_fresh_listing_does_not_become_stale_edge(self):
        signal = roi.market_momentum_signal(self.candidate(age_days=2), self.now)
        self.assertIsNotNone(signal)
        self.assertFalse(signal.stale_listing)
        self.assertFalse(signal.actionable_edge)

    def test_signal_never_changes_opportunity_economics(self):
        candidate = self.candidate()
        signal = roi.market_momentum_signal(candidate, self.now)
        estimate = watcher.MarketEstimate(
            low=100,
            central=120,
            high=130,
            kept_comparables=[],
            rejected_outliers=[],
            recent_90_count=2,
            dated_count=4,
            liquidity="moyenne",
            dispersion="faible",
            confidence="moyenne",
            adaptive_discount_pct=35,
            rationale="test",
            source_counts={"gcc": 4},
            exact_grade_count=4,
            same_grader_count=4,
        )
        op = watcher.Opportunity(
            candidate.lot, estimate, 41.7, 78.0, [], []
        )
        before = (op.estimate.low, op.estimate.central, op.estimate.high, op.max_recommended)
        setattr(op, "stale_momentum_signal", signal)
        _ = roi._momentum_block(op)
        after = (op.estimate.low, op.estimate.central, op.estimate.high, op.max_recommended)
        self.assertEqual(before, after)

    def test_expected_profit_is_not_part_of_module(self):
        self.assertFalse(hasattr(roi, "expected_profit_score"))
        self.assertFalse(hasattr(roi, "EXPECTED_PROFIT"))


if __name__ == "__main__":
    unittest.main()
