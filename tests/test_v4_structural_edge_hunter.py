from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import watcher
import v4_structural_edge_hunter as edge


class StructuralEdgeHunterTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)

    def lot(self, *, grader="PSA", grade="10", price=60.0, url="https://gradedcardcenter.com/item/a"):
        return watcher.Lot(
            url=url,
            title=f"{grader} {grade} Pikachu",
            current_price=price,
            source_type="fixed",
            grader=grader,
            grade=grade,
            card_number="25/102",
            card_set="Base Set",
            language="French",
        )

    def sale(self, price, *, grader="PSA", grade=10.0, days=10, source="gcc"):
        return watcher.ComparableSale(
            price=float(price),
            source=source,
            grader=grader,
            grade=float(grade),
            sold_at=self.now - timedelta(days=days),
            exact_card=True,
            match_score=100,
            proven_commercial_dimensions=(
                ("language:fr",) if source != "gcc" else ()
            ),
        )

    def estimate(self, low=90, central=100, high=110):
        return watcher.MarketEstimate(
            low=float(low),
            central=float(central),
            high=float(high),
            kept_comparables=[],
            rejected_outliers=[],
            recent_90_count=3,
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

    def opportunity(self, lot=None, gcc=None, ebay=None, apr=None):
        lot = lot or self.lot()
        return watcher.Opportunity(
            lot=lot,
            estimate=self.estimate(),
            discount_pct=40.0,
            max_recommended=65.0,
            gcc_comparables=list(gcc or []),
            ebay_comparables=list(ebay or []),
            psa_apr_comparables=list(apr or []),
        )

    def candidate(self, lot=None, sales=None):
        return SimpleNamespace(
            lot=lot or self.lot(),
            gcc=SimpleNamespace(sales=list(sales or [])),
        )

    def test_seller_identity_requires_explicit_field(self):
        self.assertEqual(edge._seller_key_from_result({"id": "listing-123"}), "")
        self.assertEqual(
            edge._seller_key_from_result({"seller": {"id": "seller-7"}}),
            "seller:id:seller-7",
        )

    def test_cross_market_lag_uses_exact_dated_external_sold(self):
        lot = self.lot(price=60)
        gcc = [
            self.sale(75, days=120),
            self.sale(80, days=150),
        ]
        ebay = [
            self.sale(110, days=10, source="ebay"),
            self.sale(120, days=20, source="ebay"),
        ]
        op = self.opportunity(lot, gcc, ebay)
        signal = edge.cross_market_lag_signal(op, self.now)
        self.assertIsNotNone(signal)
        self.assertGreater(signal.market_lag_pct, 30)
        self.assertGreater(signal.price_gap_pct, 40)

    def test_cross_market_lag_sparse_external_fails_closed(self):
        op = self.opportunity(
            self.lot(price=60),
            [self.sale(75, days=120), self.sale(80, days=150)],
            [self.sale(120, days=10, source="ebay")],
        )
        self.assertIsNone(edge.cross_market_lag_signal(op, self.now))

    def test_grader_lag_requires_historical_spread_and_psa_momentum(self):
        lot = self.lot(grader="PCA", grade="9", price=70)
        sales = [
            self.sale(72, grader="PCA", grade=9, days=150),
            self.sale(76, grader="PCA", grade=9, days=180),
            self.sale(80, grader="PSA", grade=9, days=150),
            self.sale(84, grader="PSA", grade=9, days=180),
            self.sale(120, grader="PSA", grade=9, days=10),
            self.sale(124, grader="PSA", grade=9, days=20),
        ]
        signal = edge.grader_lag_signal(self.candidate(lot, sales), self.now)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.target_grader, "PCA")
        self.assertGreater(signal.psa_momentum_pct, 40)
        self.assertGreater(signal.current_gap_pct, 20)

    def test_grader_lag_does_not_mix_wrong_grade(self):
        lot = self.lot(grader="PCA", grade="9", price=60)
        sales = [
            self.sale(75, grader="PCA", grade=8, days=150),
            self.sale(77, grader="PCA", grade=8, days=180),
            self.sale(80, grader="PSA", grade=9, days=150),
            self.sale(85, grader="PSA", grade=9, days=180),
            self.sale(120, grader="PSA", grade=9, days=10),
            self.sale(125, grader="PSA", grade=9, days=20),
        ]
        self.assertIsNone(edge.grader_lag_signal(self.candidate(lot, sales), self.now))

    def test_liquidity_breakout_detects_recent_cluster(self):
        lot = self.lot(price=65)
        sales = [
            self.sale(100, days=5),
            self.sale(105, days=15),
            self.sale(110, days=30),
            self.sale(80, days=150),
        ]
        signal = edge.liquidity_breakout_signal(self.candidate(lot, sales), self.now)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.recent_count, 3)
        self.assertEqual(signal.prior_count, 1)

    def test_liquidity_breakout_rejects_already_liquid_history(self):
        lot = self.lot(price=65)
        sales = [
            self.sale(100, days=5),
            self.sale(105, days=15),
            self.sale(110, days=30),
            self.sale(75, days=100),
            self.sale(80, days=150),
            self.sale(85, days=200),
        ]
        self.assertIsNone(edge.liquidity_breakout_signal(self.candidate(lot, sales), self.now))

    def test_relative_grade_anomaly_uses_same_grader_lower_grade(self):
        lot = self.lot(grader="PCA", grade="9.5", price=70)
        sales = [
            self.sale(90, grader="PCA", grade=9, days=20),
            self.sale(100, grader="PCA", grade=9, days=40),
            self.sale(150, grader="PSA", grade=9, days=20),
        ]
        signal = edge.relative_grade_anomaly_signal(self.candidate(lot, sales), self.now)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.lower_grade, 9.0)
        self.assertGreater(signal.inversion_pct, 20)

    def test_same_card_inventory_requires_second_exact_ask_and_recent_sold(self):
        first = self.lot(price=60, url="https://gradedcardcenter.com/item/a")
        second = self.lot(price=90, url="https://gradedcardcenter.com/item/b")
        sales = [self.sale(100, days=10), self.sale(105, days=20)]
        with patch.object(watcher, "commercial_identity_is_sufficient", return_value=True), \
             patch.object(watcher, "external_commercial_identity_key", return_value="strict-key"):
            signal = edge.same_card_inventory_signal(
                self.candidate(first, sales), [first, second], self.now
            )
        self.assertIsNotNone(signal)
        self.assertGreater(signal.inventory_gap_pct, 30)
        self.assertGreater(signal.sold_gap_pct, 30)

    def test_stale_seller_repricing_requires_explicit_seller_portfolio(self):
        lot = self.lot(price=60)
        setattr(lot, "gcc_seller_key", "seller:id:7")
        setattr(lot, "gcc_created_at", self.now - timedelta(days=30))
        second = self.lot(price=55, url="https://gradedcardcenter.com/item/b")
        setattr(second, "gcc_seller_key", "seller:id:7")
        setattr(second, "gcc_created_at", self.now - timedelta(days=25))
        sales = [
            self.sale(120, days=10),
            self.sale(130, days=20),
            self.sale(80, days=120),
            self.sale(90, days=150),
        ]
        signal = edge.stale_seller_repricing_signal(
            self.candidate(lot, sales), [lot, second], self.now
        )
        self.assertIsNotNone(signal)
        self.assertEqual(signal.stale_fixed_count, 2)

    def test_expected_profit_is_information_only(self):
        op = self.opportunity(self.lot(price=50))
        before = (
            op.discount_pct,
            op.max_recommended,
            op.estimate.low,
            op.estimate.central,
            op.estimate.high,
        )
        info = edge.expected_profit_info(op)
        after = (
            op.discount_pct,
            op.max_recommended,
            op.estimate.low,
            op.estimate.central,
            op.estimate.high,
        )
        self.assertIsNotNone(info)
        self.assertEqual(before, after)
        self.assertGreater(info.central_profit_eur, 0)

    def test_expected_profit_ranking_never_removes_opportunities(self):
        op1 = self.opportunity(self.lot(price=50, url="a"))
        op2 = self.opportunity(self.lot(price=80, url="b"))
        original = [op1, op2]
        edge._ORIGINAL_PROCESS = lambda *args, **kwargs: original
        result = edge._process_with_structural_edges(
            None, [], {}, None, None, self.now
        )
        self.assertEqual(result, original)
        self.assertEqual(len(result), 2)

    def test_auction_priority_never_gets_structural_bonus(self):
        lot = self.lot()
        lot.source_type = "auction"
        candidate = self.candidate(lot, [])
        edge._ORIGINAL_PRIORITY_SCORE = lambda _candidate: 123.0
        self.assertEqual(edge._priority_score_with_structural_edges(candidate), 123.0)

    def test_notification_block_labels_asks_and_expected_profit_safely(self):
        op = self.opportunity(self.lot(price=50))
        setattr(
            op,
            "expected_profit_info",
            edge.ExpectedProfitInfo(50, 40, 100, 80, 0, 0, 1, 1),
        )
        setattr(
            op,
            "same_card_inventory_signal",
            edge.SameCardInventorySignal(50, 80, 37.5, 100, 3, 50, 2),
        )
        setattr(
            op,
            "exact_active_ask",
            SimpleNamespace(price=90.0),
        )
        block = edge._structural_block(op)
        self.assertIn("ASK, PAS UNE VENTE", block)
        self.assertIn("JAMAIS UN FILTRE", block)
        self.assertIn("Une forte décote reste notifiée", block)


if __name__ == "__main__":
    unittest.main()
