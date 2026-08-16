import unittest
from datetime import datetime, timedelta, timezone

from v4_global_market_core import (
    ACTIVE_AUCTION,
    EBAY_GRADED_AGGREGATE,
    FIXED_ASK,
    CommercialIdentity,
    all_in_eur,
    build_fair_value,
)
from v4_global_poketrace_bridge import poketrace_estimate_to_aggregate
from v4_global_ppt_bridge import ppt_metrics_to_aggregate
from v4_market_gcc_bridge import gcc_offer_to_observation
from v4_market_magi_bridge import magi_fixed_ask_to_observation

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
ID = CommercialIdentity("Pikachu", "Pokemon 151", "173/165", "ja", "PSA", "10")
FR = CommercialIdentity("Pikachu", "Pokemon 151", "173/165", "fr", "PSA", "10")
FX = {"JPY": 170.0}


class GlobalEvidenceBridgeTests(unittest.TestCase):
    def test_ppt_metrics_stay_aggregated_and_can_be_recent(self):
        row = ppt_metrics_to_aggregate(
            ID,
            {
                "evidence_class": "SOLD_AGGREGATED",
                "fair_value_eur": 90,
                "sales_count": 193,
                "last_sale_age_days": 3,
                "recent_90_count": 100,
            },
            observed_at=NOW,
            identity_proven=True,
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.correlation_family, EBAY_GRADED_AGGREGATE)
        self.assertEqual(row.last_sale_at, NOW - timedelta(days=3))
        fair = build_fair_value(ID, [], now=NOW, currency_per_eur={}, aggregate_evidence=[row])
        self.assertIsNotNone(fair)
        self.assertEqual(fair.method, "RECENT_EXACT_SOLD_AGGREGATE")

    def test_ppt_bridge_rejects_unproven_or_french_identity(self):
        metrics = {"fair_value_eur": 90, "sales_count": 10, "last_sale_age_days": 1}
        self.assertIsNone(ppt_metrics_to_aggregate(ID, metrics, observed_at=NOW, identity_proven=False))
        self.assertIsNone(ppt_metrics_to_aggregate(FR, metrics, observed_at=NOW, identity_proven=True))

    def test_poketrace_without_last_sale_cannot_drive_recent_fair(self):
        row = poketrace_estimate_to_aggregate(
            ID,
            {"central": 95, "low": 90, "high": 100, "exact_grade_count": 20},
            observed_at=NOW,
            identity_proven=True,
        )
        self.assertIsNotNone(row)
        self.assertIsNone(row.last_sale_at)
        fair = build_fair_value(ID, [], now=NOW, currency_per_eur={}, aggregate_evidence=[row])
        self.assertIsNone(fair)

    def test_gcc_unknown_fee_fails_closed(self):
        row = gcc_offer_to_observation(
            identity=ID,
            price_eur=50,
            observed_at=NOW,
            source_id="gcc-1",
            offer_type="fixed",
            identity_proven=True,
            buyer_fee_rate=None,
        )
        self.assertEqual(row.evidence_type, FIXED_ASK)
        self.assertIsNone(all_in_eur(row, {}))

    def test_gcc_active_auction_remains_weak(self):
        row = gcc_offer_to_observation(
            identity=ID,
            price_eur=20,
            observed_at=NOW,
            source_id="gcc-a",
            offer_type="auction",
            identity_proven=True,
            buyer_fee_rate=0.0,
            within_five_minutes=False,
        )
        self.assertEqual(row.evidence_type, ACTIVE_AUCTION)
        self.assertFalse(row.is_actionable_offer)

    def test_magi_uses_explicit_all_in_economics(self):
        row = magi_fixed_ask_to_observation(
            identity=ID,
            price_jpy=10000,
            observed_at=NOW,
            source_id="magi-1",
            identity_proven=True,
            buyer_fee_rate=0.03,
            logistics_jpy=500,
        )
        self.assertEqual(row.evidence_type, FIXED_ASK)
        self.assertAlmostEqual(all_in_eur(row, FX), (10000 * 1.03 + 500) / 170)


if __name__ == "__main__":
    unittest.main()
