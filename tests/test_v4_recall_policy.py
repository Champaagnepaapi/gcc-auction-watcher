from __future__ import annotations

import os
import unittest
from unittest import mock

import v4_recall_policy as recall


class RecallPolicyTests(unittest.TestCase):
    def test_psa_scope_includes_lower_numeric_grades_but_not_9_5(self):
        self.assertIn(7.0, recall.PSA_RECALL_GRADES)
        self.assertIn(8.5, recall.PSA_RECALL_GRADES)
        self.assertIn(10.0, recall.PSA_RECALL_GRADES)
        self.assertNotIn(9.5, recall.PSA_RECALL_GRADES)

    def test_high_volume_exact_undated_aggregate_requires_25_percent(self):
        with mock.patch.dict(os.environ, {"V4_RECALL_MIN_DISCOUNT_PCT": "20"}):
            threshold = recall.recall_adaptive_discount_threshold(
                305,
                "faible",
                "élevée",
                0,
                0,
                305,
                True,
                False,
            )
        self.assertEqual(threshold, 25.0)

    def test_high_volume_recent_exact_market_can_act_at_20_percent(self):
        with mock.patch.dict(os.environ, {"V4_RECALL_MIN_DISCOUNT_PCT": "20"}):
            threshold = recall.recall_adaptive_discount_threshold(
                12,
                "faible",
                "élevée",
                10,
                12,
                12,
                True,
                False,
            )
        self.assertEqual(threshold, 20.0)

    def test_cross_grader_uncertainty_adds_premium_without_blanket_rejection(self):
        with mock.patch.dict(os.environ, {"V4_RECALL_MIN_DISCOUNT_PCT": "20"}):
            threshold = recall.recall_adaptive_discount_threshold(
                12,
                "faible",
                "élevée",
                10,
                12,
                12,
                True,
                True,
            )
        self.assertEqual(threshold, 25.0)

    def test_provider_conflict_remains_more_conservative(self):
        with mock.patch.dict(os.environ, {"V4_RECALL_MIN_DISCOUNT_PCT": "20"}):
            threshold = recall.recall_adaptive_discount_threshold(
                12,
                "moyenne",
                "élevée",
                10,
                12,
                12,
                False,
                False,
            )
        self.assertEqual(threshold, 28.0)


if __name__ == "__main__":
    unittest.main()
