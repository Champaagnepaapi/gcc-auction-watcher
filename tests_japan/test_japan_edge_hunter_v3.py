from __future__ import annotations

import unittest

import japan_edge_hunter as base
import japan_edge_hunter_v3 as v3


def opportunity(*, fair=100.0, landed=60.0):
    ident = base.Identity(
        name="Bulbasaur",
        set_name="151",
        number="166/165",
        language="Japanese",
        grader="PSA",
        grade="10",
        year=2023,
    )
    return base.Opportunity(
        provider="yahoo_fleamarket",
        url="https://paypayfleamarket.yahoo.co.jp/item/z-test",
        title="Bulbasaur 166/165 PSA10 Japanese",
        price_jpy=10500,
        ask_eur=55.0,
        ask_chf=52.0,
        landed_eur=landed,
        landed_chf=57.0,
        fair_eur=fair,
        discount_pct=40.0,
        gcc_sold_count=3,
        gcc_recent_90=3,
        evidence="GCC_EXACT_SOLD_RECENT",
        identity=ident,
    )


class JapanEdgeV3Tests(unittest.TestCase):
    def test_external_lot_preserves_exact_japanese_psa10_identity(self):
        op = opportunity()
        lot = v3._lot_for_external(op)
        self.assertEqual(lot.language, "Japanese")
        self.assertEqual(lot.grader, "PSA")
        self.assertEqual(lot.grade, "10")
        self.assertEqual(lot.card_set, "151")
        self.assertEqual(lot.card_number, "166/165")

    def test_multimarket_confirmed_requires_30pct_vs_external_and_global(self):
        op = opportunity(fair=100, landed=60)
        ext = v3.ExternalReference(status="EXACT_SOLD_CONFIRMED", fair_eur=95, sold_count=8)
        decision = v3.classify_market(op, ext, 30)
        self.assertEqual(decision.status, "MULTIMARKET_CONFIRMED")
        self.assertTrue(decision.should_notify)
        self.assertGreaterEqual(decision.discount_vs_external_pct, 30)
        self.assertGreaterEqual(decision.discount_vs_global_pct, 30)

    def test_gcc_edge_is_blocked_when_global_market_does_not_confirm_discount(self):
        op = opportunity(fair=100, landed=60)
        ext = v3.ExternalReference(status="EXACT_SOLD_CONFIRMED", fair_eur=75, sold_count=8)
        decision = v3.classify_market(op, ext, 30)
        self.assertEqual(decision.status, "GCC_EDGE_NOT_GLOBAL")
        self.assertFalse(decision.should_notify)

    def test_material_market_conflict_blocks_high_priority_alert(self):
        op = opportunity(fair=120, landed=60)
        ext = v3.ExternalReference(status="EXACT_SOLD_CONFIRMED", fair_eur=70, sold_count=8)
        decision = v3.classify_market(op, ext, 30)
        self.assertEqual(decision.status, "MARKET_CONFLICT_BLOCKED")
        self.assertFalse(decision.should_notify)

    def test_missing_external_market_keeps_labelled_gcc_only_alert(self):
        op = opportunity(fair=100, landed=60)
        ext = v3.ExternalReference(status="CLEAN_NO_MATCH")
        decision = v3.classify_market(op, ext, 30)
        self.assertEqual(decision.status, "GCC_ONLY_UNCONFIRMED")
        self.assertTrue(decision.should_notify)
        self.assertIsNone(decision.external_fair_eur)


if __name__ == "__main__":
    unittest.main()
