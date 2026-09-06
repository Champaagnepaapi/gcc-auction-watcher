from __future__ import annotations

import unittest

import v4_global_marketplace_economic as economic
import v4_global_economic_confirmation as legacy
import watcher
from v4_global_market_core import FIXED_ASK


def _card(price=60.0, gcc_fair=None, market="fanatics"):
    card = {
        "identity": {
            "name": "Mewtwo",
            "set_name": "151",
            "number": "183/165",
            "language": "ja",
            "grader": "PSA",
            "grade": "10",
            "edition": "",
            "finish": "",
            "variant": "",
        },
        "offers": [
            {
                "market": market,
                "evidence_type": FIXED_ASK,
                "source_url": f"https://{market}.invalid/1",
                "all_in_eur": price,
            }
        ],
    }
    if gcc_fair is not None:
        card["fair_value_eur"] = gcc_fair
    return card


def _external(provider, fair, count=20, strength="STRONG"):
    return legacy.ExternalAggregate(
        provider=provider,
        status="MATCHED",
        fair_eur=fair,
        sold_count=count,
        evidence_strength=strength,
    )


def _pricecharting(fair=100.0):
    return legacy.ExternalAggregate(
        provider="PriceCharting guide",
        status="MATCHED",
        fair_eur=fair,
        sold_count=0,
        evidence_strength=economic.PRICECHARTING_GUIDE_STRENGTH,
        note="GUIDE only",
    )


class MarketplaceEconomicTests(unittest.TestCase):
    def test_external_only_can_confirm_edge_without_gcc_history(self):
        decision = economic.evaluate_marketplace_card(
            _card(60),
            ppt=_external("PokemonPriceTracker", 100),
            poketrace=legacy.ExternalAggregate("PokeTrace/eBay SOLD", "UNAVAILABLE"),
        )
        self.assertEqual(decision.status, "MULTIMARKET_CONFIRMED")
        self.assertTrue(decision.would_notify)
        self.assertEqual(decision.valuation_basis, "EXTERNAL_ONLY")
        self.assertEqual(decision.valuation_evidence_type, "SOLD_AGGREGATE")
        self.assertIsNone(decision.gcc_fair_eur)
        self.assertEqual(decision.confirmed_fair_eur, 100.0)

    def test_gcc_history_is_diagnostic_only_and_cannot_cap_fair_value(self):
        decision = economic.evaluate_marketplace_card(
            _card(60, gcc_fair=25),
            ppt=_external("PokemonPriceTracker", 100),
            poketrace=legacy.ExternalAggregate("PokeTrace/eBay SOLD", "UNAVAILABLE"),
        )
        self.assertEqual(decision.status, "MULTIMARKET_CONFIRMED")
        self.assertTrue(decision.would_notify)
        self.assertEqual(decision.valuation_basis, "EXTERNAL_ONLY")
        self.assertEqual(decision.gcc_fair_eur, 25.0)
        self.assertEqual(decision.confirmed_fair_eur, 100.0)
        self.assertIsNone(decision.market_ratio)
        self.assertIn("diagnostic-only", decision.note)

    def test_high_gcc_history_cannot_create_or_conflict_block_edge(self):
        decision = economic.evaluate_marketplace_card(
            _card(60, gcc_fair=500),
            ppt=_external("PokemonPriceTracker", 100),
            poketrace=legacy.ExternalAggregate("PokeTrace/eBay SOLD", "UNAVAILABLE"),
        )
        self.assertEqual(decision.status, "MULTIMARKET_CONFIRMED")
        self.assertTrue(decision.would_notify)
        self.assertEqual(decision.confirmed_fair_eur, 100.0)
        self.assertEqual(decision.valuation_basis, "EXTERNAL_ONLY")

    def test_marketplace_ask_never_becomes_fair_value(self):
        decision = economic.evaluate_marketplace_card(
            _card(60, gcc_fair=100),
            ppt=_external("PokemonPriceTracker", 80),
            poketrace=legacy.ExternalAggregate("PokeTrace/eBay SOLD", "UNAVAILABLE"),
        )
        self.assertEqual(decision.external_fair_eur, 80.0)
        self.assertEqual(decision.confirmed_fair_eur, 80.0)
        self.assertNotEqual(decision.confirmed_fair_eur, decision.offer_all_in_eur)
        payload = economic.decision_payload(decision)
        self.assertFalse(payload["marketplace_listing_is_valuation"])
        self.assertTrue(payload["marketplace_sources_are_opportunity_only"])
        self.assertFalse(payload["gcc_history_economic_authority"])
        self.assertFalse(payload["ask_is_sold"])

    def test_same_offer_is_evaluated_identically_regardless_of_vault(self):
        results = []
        for market in ("gcc", "fanatics", "comc", "magi", "cardova"):
            decision = economic.evaluate_marketplace_card(
                _card(60, market=market),
                ppt=_external("PokemonPriceTracker", 100),
                poketrace=legacy.ExternalAggregate("PokeTrace/eBay SOLD", "UNAVAILABLE"),
            )
            results.append(
                (
                    decision.confirmed_fair_eur,
                    decision.discount_pct,
                    decision.required_discount_pct,
                    decision.would_notify,
                )
            )
        self.assertEqual(len(set(results)), 1)

    def test_pricecharting_guide_fallback_uses_normal_v4_discount(self):
        yes = economic.evaluate_marketplace_card(
            _card(65),
            ppt=legacy.ExternalAggregate("PokemonPriceTracker", "UNAVAILABLE"),
            poketrace=legacy.ExternalAggregate("PokeTrace/eBay SOLD", "UNAVAILABLE"),
            pricecharting=_pricecharting(100),
        )
        no = economic.evaluate_marketplace_card(
            _card(75),
            ppt=legacy.ExternalAggregate("PokemonPriceTracker", "UNAVAILABLE"),
            poketrace=legacy.ExternalAggregate("PokeTrace/eBay SOLD", "UNAVAILABLE"),
            pricecharting=_pricecharting(100),
        )
        self.assertTrue(yes.would_notify)
        self.assertEqual(yes.valuation_basis, "PRICECHARTING_GUIDE_ONLY")
        self.assertEqual(yes.valuation_evidence_type, "PRICE_GUIDE")
        self.assertEqual(yes.required_discount_pct, legacy.DEFAULT_MIN_DISCOUNT)
        self.assertEqual(yes.external_sales_count, 0)
        self.assertFalse(no.would_notify)
        self.assertEqual(no.status, "NO_GLOBAL_EDGE")

    def test_strong_sold_aggregate_precedes_pricecharting_guide(self):
        decision = economic.evaluate_marketplace_card(
            _card(60),
            ppt=_external("PokemonPriceTracker", 100),
            poketrace=legacy.ExternalAggregate("PokeTrace/eBay SOLD", "UNAVAILABLE"),
            pricecharting=_pricecharting(500),
        )
        self.assertEqual(decision.external_provider, "PokemonPriceTracker")
        self.assertEqual(decision.confirmed_fair_eur, 100.0)
        self.assertEqual(decision.valuation_basis, "EXTERNAL_ONLY")

    def test_correlated_provider_conflict_stays_blocked_even_with_guide(self):
        decision = economic.evaluate_marketplace_card(
            _card(60),
            ppt=_external("PokemonPriceTracker", 100),
            poketrace=_external("PokeTrace/eBay SOLD", 150, strength=watcher.EVIDENCE_STRONG),
            pricecharting=_pricecharting(105),
        )
        self.assertEqual(decision.status, "MARKET_CONFLICT_BLOCKED")
        self.assertFalse(decision.would_notify)

    def test_external_requires_minimum_sales_without_guide(self):
        decision = economic.evaluate_marketplace_card(
            _card(60),
            ppt=_external("PokemonPriceTracker", 100, count=2),
            poketrace=legacy.ExternalAggregate("PokeTrace/eBay SOLD", "UNAVAILABLE"),
        )
        self.assertEqual(decision.status, "NO_EXTERNAL_CONFIRMATION")
        self.assertFalse(decision.would_notify)
        self.assertEqual(decision.valuation_basis, "EXTERNAL_ONLY")


if __name__ == "__main__":
    unittest.main()
