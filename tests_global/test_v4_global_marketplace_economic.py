from __future__ import annotations

import unittest

import v4_global_marketplace_economic as economic
import v4_global_economic_confirmation as legacy
import watcher
from v4_global_market_core import FIXED_ASK


def _card(price=60.0, gcc_fair=None):
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
                "market": "fanatics",
                "evidence_type": FIXED_ASK,
                "source_url": "https://example.invalid/1",
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
        self.assertFalse(payload["gcc_history_economic_authority"])
        self.assertFalse(payload["ask_is_sold"])

    def test_correlated_provider_conflict_stays_blocked(self):
        decision = economic.evaluate_marketplace_card(
            _card(60),
            ppt=_external("PokemonPriceTracker", 100),
            poketrace=_external("PokeTrace/eBay SOLD", 150, strength=watcher.EVIDENCE_STRONG),
        )
        self.assertEqual(decision.status, "MARKET_CONFLICT_BLOCKED")
        self.assertFalse(decision.would_notify)

    def test_external_requires_minimum_sales(self):
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