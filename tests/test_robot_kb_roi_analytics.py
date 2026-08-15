from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

import robot_kb_roi_analytics as analytics


class RobotKbRoiAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
        self.claims = {
            "card_title_raw": json.dumps("PSA 10 Pikachu Holo"),
            "set": json.dumps("Set de base"),
            "collector_number": json.dumps("#25/102"),
            "language": json.dumps("French"),
            "edition": json.dumps("Edition 1"),
            "grader": json.dumps("PSA"),
            "grade": json.dumps("10"),
        }

    def sale(self, grader: str, grade: float, price: float, age_days: int, key: str) -> analytics.SaleRow:
        return analytics.SaleRow(
            occurred_at=self.now - timedelta(days=age_days),
            amount_minor=round(price * 100),
            currency="EUR",
            card_key=key,
            identity_hash=analytics.identity_hash(key),
            grader=grader,
            grade=grade,
        )

    def test_strict_card_key_requires_all_identity_dimensions(self):
        key = analytics.strict_card_key(self.claims)
        self.assertTrue(key)
        payload = json.loads(key)
        self.assertEqual(payload["title"], "pikachu holo")
        self.assertEqual(payload["number"], "25 102")

        incomplete = dict(self.claims)
        incomplete["edition"] = json.dumps("")
        self.assertEqual(analytics.strict_card_key(incomplete), "")

    def test_strict_card_key_keeps_visible_holo_separate(self):
        holo = analytics.strict_card_key(self.claims)
        regular_claims = dict(self.claims)
        regular_claims["card_title_raw"] = json.dumps("PSA 10 Pikachu")
        regular = analytics.strict_card_key(regular_claims)
        self.assertNotEqual(holo, regular)

    def test_depth_readiness_is_exact_tier_and_recent_sale_based(self):
        key = analytics.strict_card_key(self.claims)
        rows = [
            self.sale("PSA", 10.0, 100, 10, key),
            self.sale("PSA", 10.0, 105, 30, key),
            self.sale("PSA", 10.0, 90, 150, key),
            self.sale("PSA", 9.0, 60, 10, key),
        ]
        summary = analytics._depth_summary(rows, self.now)
        self.assertEqual(summary["distinct_exact_slab_tiers"], 2)
        self.assertEqual(summary["tiers_with_3plus_sales"], 1)
        self.assertEqual(summary["kb_first_ready_tiers"], 1)

    def test_grader_spread_requires_same_card_same_grade_and_enough_sales(self):
        key = analytics.strict_card_key(self.claims)
        rows = [
            self.sale("PSA", 10.0, 100, 30, key),
            self.sale("PSA", 10.0, 110, 60, key),
            self.sale("PCA", 10.0, 80, 35, key),
            self.sale("PCA", 10.0, 90, 65, key),
            # Wrong grade must not enter the PSA10/PCA10 ratio.
            self.sale("PCA", 9.0, 200, 35, key),
        ]
        spreads = analytics.learn_grader_spreads(rows)
        self.assertEqual(len(spreads), 1)
        spread = spreads[0]
        self.assertEqual(spread.source_grader, "PSA")
        self.assertEqual(spread.target_grader, "PCA")
        self.assertEqual(spread.grade, 10.0)
        self.assertEqual(spread.source_n, 2)
        self.assertEqual(spread.target_n, 2)
        self.assertAlmostEqual(spread.target_per_source_ratio, 85 / 105, places=4)

    def test_grader_spread_does_not_synthesize_fx_or_cross_long_window(self):
        key = analytics.strict_card_key(self.claims)
        rows = [
            self.sale("PSA", 10.0, 100, 10, key),
            self.sale("PSA", 10.0, 110, 20, key),
            self.sale("PCA", 10.0, 80, 400, key),
            self.sale("PCA", 10.0, 90, 410, key),
        ]
        self.assertEqual(analytics.learn_grader_spreads(rows), [])

        gbp = self.sale("PCA", 10.0, 90, 15, key)
        object.__setattr__(gbp, "currency", "GBP")
        rows = [
            self.sale("PSA", 10.0, 100, 10, key),
            self.sale("PSA", 10.0, 110, 20, key),
            gbp,
            self.sale("PCA", 10.0, 80, 15, key),
        ]
        self.assertEqual(analytics.learn_grader_spreads(rows), [])

    def test_expected_profit_and_v4_economic_use_are_explicitly_disabled(self):
        self.assertFalse(hasattr(analytics, "expected_profit_score"))
        self.assertFalse(hasattr(analytics, "EXPECTED_PROFIT"))


if __name__ == "__main__":
    unittest.main()
