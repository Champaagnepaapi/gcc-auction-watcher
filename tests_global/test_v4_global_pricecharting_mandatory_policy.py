from __future__ import annotations

import unittest
from unittest.mock import patch

import v4_global_economic_confirmation as legacy
import v4_global_marketplace_economic as economic
from v4_global_market_core import FIXED_ASK


def _card(price=65.0):
    return {
        "identity": {
            "name": "Poochyena",
            "set_name": "VSTAR Universe",
            "number": "208/172",
            "language": "ja",
            "grader": "PSA",
            "grade": "9",
            "edition": "",
            "finish": "",
            "variant": "",
        },
        "offers": [
            {
                "market": "gcc",
                "evidence_type": FIXED_ASK,
                "source_url": "https://example.invalid/poochyena",
                "all_in_eur": price,
            }
        ],
    }


def _unavailable(provider):
    return legacy.ExternalAggregate(provider, "UNAVAILABLE")


def _sold(provider, fair, count=10):
    return legacy.ExternalAggregate(
        provider,
        "MATCHED",
        fair_eur=fair,
        sold_count=count,
        evidence_strength="STRONG",
    )


def _guide(fair):
    return legacy.ExternalAggregate(
        "PriceCharting guide",
        "MATCHED",
        fair_eur=fair,
        sold_count=0,
        evidence_strength=economic.PRICECHARTING_GUIDE_STRENGTH,
    )


class GlobalMandatoryPriceChartingPolicyTests(unittest.TestCase):
    def test_pricecharting_guide_alone_uses_normal_30pct_floor(self):
        with patch.object(
            economic,
            "PRICECHARTING_MIN_DISCOUNT_PCT",
            legacy.DEFAULT_MIN_DISCOUNT,
        ):
            decision = economic.evaluate_marketplace_card(
                _card(65.0),
                ppt=_unavailable("PokemonPriceTracker"),
                poketrace=_unavailable("PokeTrace/eBay SOLD"),
                pricecharting=_guide(100.0),
            )
        self.assertEqual(decision.status, "MULTIMARKET_CONFIRMED")
        self.assertTrue(decision.would_notify)
        self.assertEqual(decision.valuation_basis, "PRICECHARTING_GUIDE_ONLY")
        self.assertEqual(decision.valuation_evidence_type, "PRICE_GUIDE")
        self.assertEqual(decision.required_discount_pct, legacy.DEFAULT_MIN_DISCOUNT)
        self.assertEqual(decision.confirmed_fair_eur, 100.0)

    def test_stronger_sold_derived_evidence_keeps_priority_over_guide(self):
        with patch.object(
            economic,
            "PRICECHARTING_MIN_DISCOUNT_PCT",
            legacy.DEFAULT_MIN_DISCOUNT,
        ):
            decision = economic.evaluate_marketplace_card(
                _card(65.0),
                ppt=_sold("PokemonPriceTracker", 100.0),
                poketrace=_unavailable("PokeTrace/eBay SOLD"),
                pricecharting=_guide(200.0),
            )
        self.assertEqual(decision.external_provider, "PokemonPriceTracker")
        self.assertEqual(decision.confirmed_fair_eur, 100.0)
        self.assertEqual(decision.valuation_evidence_type, "SOLD_AGGREGATE")


if __name__ == "__main__":
    unittest.main()
