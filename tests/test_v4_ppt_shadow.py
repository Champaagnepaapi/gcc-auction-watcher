from __future__ import annotations

import unittest
from datetime import date, timedelta

from v4_ppt_shadow_model import (
    BASE_REQUIRED_DISCOUNT_PCT,
    EVIDENCE_CLASS,
    DailyGradePoint,
    GradedAggregate,
    ShadowInput,
    analyze_shadow,
    grader_premium_vs_psa_pct,
    temporal_fair_value_usd,
    temporal_grader_premium_vs_psa,
)
from v4_ppt_shadow_provider import (
    PptMacroIdentity,
    PptRequestBudget,
    match_macro_identity,
)


def rising_history(
    anchor=date(2026, 8, 14),
    days=180,
    base=100.0,
    daily_gain=0.35,
):
    rows = []
    for age in range(days - 1, -1, -3):
        when = anchor - timedelta(days=age)
        price = base + (days - age) * daily_gain
        rows.append(DailyGradePoint(when.isoformat(), 2, price, price * 2))
    return rows


class PptShadowModelTests(unittest.TestCase):
    def aggregate(self, **overrides):
        data = dict(
            grader="PSA",
            grade="10",
            sales_count=80,
            average_price_usd=205.0,
            median_price_usd=200.0,
            smart_market_price_usd=202.0,
            last_sale_date="2026-08-14",
            market_trend="UP",
        )
        data.update(overrides)
        return GradedAggregate(**data)

    def target(self, **overrides):
        data = dict(
            identity_exact=True,
            microvariant_compatible=True,
            grader="PSA",
            grade="10",
            gcc_price_eur=160.0,
            usd_per_eur=1.0,
            gcc_exact_sold_count=0,
        )
        data.update(overrides)
        return ShadowInput(**data)

    def test_evidence_is_aggregate_not_item_level(self):
        result = analyze_shadow(
            self.target(), self.aggregate(), rising_history(), today=date(2026, 8, 15)
        )
        self.assertEqual(result.evidence_class, EVIDENCE_CLASS)
        self.assertNotEqual(result.evidence_class, "SOLD_ITEM_LEVEL")

    def test_exact_identity_and_microvariant_are_mandatory(self):
        result = analyze_shadow(
            self.target(microvariant_compatible=False),
            self.aggregate(),
            rising_history(),
            today=date(2026, 8, 15),
        )
        self.assertFalse(result.eligible)
        self.assertIsNone(result.fair_value_eur)

    def test_external_value_is_still_computed_when_gcc_has_solds(self):
        result = analyze_shadow(
            self.target(gcc_exact_sold_count=8),
            self.aggregate(),
            rising_history(),
            today=date(2026, 8, 15),
        )
        self.assertTrue(result.eligible)
        self.assertTrue(result.gcc_history_present)
        self.assertGreater(result.fair_value_eur, 0)

    def test_recent_market_level_reprices_stale_provider_center(self):
        history = rising_history(base=100.0, daily_gain=1.0)
        fair, recent30, recent90 = temporal_fair_value_usd(
            self.aggregate(
                average_price_usd=130.0,
                median_price_usd=125.0,
                smart_market_price_usd=130.0,
            ),
            history,
        )
        self.assertIsNotNone(recent30)
        self.assertIsNotNone(recent90)
        self.assertGreater(fair, 130.0)

    def test_strong_momentum_can_lower_shadow_threshold_but_not_baseline(self):
        result = analyze_shadow(
            self.target(gcc_price_eur=160.0),
            self.aggregate(
                median_price_usd=200.0,
                smart_market_price_usd=200.0,
                average_price_usd=200.0,
            ),
            rising_history(base=60.0, daily_gain=1.0),
            today=date(2026, 8, 15),
        )
        self.assertFalse(result.baseline_30pct_signal)
        self.assertGreater(result.kinetic_bonus_pp, 0)
        self.assertLess(result.shadow_required_discount_pct, BASE_REQUIRED_DISCOUNT_PCT)

    def test_low_volume_never_gets_kinetic_bonus(self):
        result = analyze_shadow(
            self.target(),
            self.aggregate(sales_count=3),
            rising_history(),
            today=date(2026, 8, 15),
        )
        self.assertEqual(result.kinetic_bonus_pp, 0.0)
        self.assertEqual(result.shadow_required_discount_pct, BASE_REQUIRED_DISCOUNT_PCT)

    def test_static_grader_premium(self):
        self.assertAlmostEqual(grader_premium_vs_psa_pct(90.0, 100.0), -10.0)

    def test_temporal_grader_premium_has_all_windows(self):
        target = rising_history(base=90.0, daily_gain=0.25)
        psa = rising_history(base=100.0, daily_gain=0.25)
        result = temporal_grader_premium_vs_psa(target, psa)
        self.assertEqual(set(result), {"30d", "90d", "180d"})
        self.assertTrue(all(value is not None for value in result.values()))

    def test_external_catalog_id_is_strongest_macro_proof(self):
        identity = PptMacroIdentity(
            "swsh7-215", "Umbreon VMAX", "Evolving Skies", "215"
        )
        rows = [
            {
                "externalCatalogId": "swsh7-215",
                "name": "Umbreon VMAX (Alternate Art Secret)",
                "setName": "Evolving Skies",
                "cardNumber": "215",
            }
        ]
        result = match_macro_identity(identity, rows)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.proof, "EXTERNAL_CATALOG_ID")

    def test_ambiguous_set_number_never_guesses(self):
        identity = PptMacroIdentity("base1-4", "Charizard", "Base Set", "4")
        rows = [
            {"setName": "Base Set", "cardNumber": "4", "name": "Charizard A"},
            {"setName": "Base Set", "cardNumber": "4", "name": "Charizard B"},
        ]
        result = match_macro_identity(identity, rows)
        self.assertEqual(result.status, "AMBIGUOUS")

    def test_budget_fails_closed_at_daily_floor(self):
        budget = PptRequestBudget(
            max_http_calls=12,
            credit_cap=60,
            daily_remaining_floor=15000,
        )
        budget.record(
            {
                "X-Api-Calls-Consumed": "5",
                "X-Ratelimit-Daily-Remaining": "15000",
            }
        )
        self.assertFalse(budget.can_call())
        self.assertEqual(budget.blocked_reason, "DAILY_REMAINING_SAFETY_FLOOR")

    def test_budget_fails_closed_without_quota_headers(self):
        budget = PptRequestBudget()
        budget.record({})
        self.assertFalse(budget.can_call())
        self.assertEqual(budget.blocked_reason, "CREDIT_HEADER_REQUIRED")


if __name__ == "__main__":
    unittest.main()
