from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import japan_edge_full_market as full
import japan_edge_hunter as base
import japan_edge_hunter_v3 as v3
import watcher


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

    def test_notification_shows_japan_gcc_external_and_multimarket_prices_separately(self):
        op = opportunity(fair=100, landed=50)
        ext = v3.ExternalReference(
            status="EXACT_SOLD_CONFIRMED",
            fair_eur=80,
            sold_count=7,
            source="eBay SOLD family + PSA APR",
        )
        decision = v3.classify_market(op, ext, 30)
        response = Mock()
        response.raise_for_status.return_value = None
        with patch.object(v3.requests, "post", return_value=response) as post:
            v3.notify(op, ext, decision, "https://ntfy.sh", "topic")

        body = post.call_args.kwargs["data"].decode()
        self.assertIn("Prix Japon: ¥10,500 | rendu estimé 57 CHF", body)
        self.assertIn("GCC exact JP PSA10: €100", body)
        self.assertIn("→ décote vs GCC: -50%", body)
        self.assertIn("Marché externe exact: €80", body)
        self.assertIn("→ décote vs externe: -38%", body)
        self.assertIn("Fair multi-marché: €90", body)
        self.assertIn("→ décote globale: -44%", body)
        self.assertIn("VERDICT: MULTIMARKET_CONFIRMED", body)
        self.assertIn("ASK, PAS UNE VENTE", body)

    def test_psa_apr_requires_explicit_japanese_provenance(self):
        good = watcher.ComparableSale(
            100, source="psa", grader="PSA", grade=10, exact_card=True,
            proven_commercial_dimensions=("language:japanese",),
        )
        missing_language = watcher.ComparableSale(
            100, source="psa", grader="PSA", grade=10, exact_card=True,
            proven_commercial_dimensions=(),
        )
        self.assertTrue(full._exact_japanese_psa10_sale(good, require_provenance=True))
        self.assertFalse(full._exact_japanese_psa10_sale(missing_language, require_provenance=True))

    def test_direct_ebay_requires_explicit_japanese_psa10(self):
        good = watcher.ComparableSale(
            100, source="ebay", grader="PSA", grade=10, exact_card=True,
            match_score=90, context="eBay SOLD | Pokemon 151 Bulbasaur 166/165 Japanese PSA 10",
        )
        wrong_language = watcher.ComparableSale(
            100, source="ebay", grader="PSA", grade=10, exact_card=True,
            match_score=90, context="eBay SOLD | Pokemon 151 Bulbasaur 166/165 English PSA 10",
        )
        wrong_grade = watcher.ComparableSale(
            100, source="ebay", grader="PSA", grade=9, exact_card=True,
            match_score=90, context="eBay SOLD | Pokemon 151 Bulbasaur 166/165 Japanese PSA 9",
        )
        self.assertTrue(full._exact_japanese_psa10_sale(good, require_provenance=False))
        self.assertFalse(full._exact_japanese_psa10_sale(wrong_language, require_provenance=False))
        self.assertFalse(full._exact_japanese_psa10_sale(wrong_grade, require_provenance=False))


if __name__ == "__main__":
    unittest.main()
