from __future__ import annotations

import unittest

from v5.pokemonpricetracker_adapter import (
    CanonicalPptIdentity,
    cardmarket_eur,
    daily_grade_history,
    graded_aggregate,
    match_macro_identity,
    raw_usd,
    total_ebay_sales,
)


class PokemonPriceTrackerAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.card = CanonicalPptIdentity("swsh7-215", "Umbreon VMAX", "Evolving Skies", "215", "en")

    def test_external_catalog_id_resolves_descriptor_rich_name(self) -> None:
        row = {
            "externalCatalogId": "swsh7-215",
            "name": "Umbreon VMAX (Alternate Art Secret)",
            "setName": "SWSH07: Evolving Skies",
            "cardNumber": "215/203",
        }
        match = match_macro_identity(self.card, [row])
        self.assertEqual(match.status, "EXACT")
        self.assertEqual(match.proof, "EXTERNAL_CATALOG_ID")

    def test_set_number_fallback_resolves_without_exact_provider_name(self) -> None:
        row = {"name": "Umbreon VMAX Alt Art", "setName": "SWSH07: Evolving Skies", "cardNumber": "215/203"}
        match = match_macro_identity(self.card, [row])
        self.assertEqual(match.status, "EXACT")
        self.assertEqual(match.proof, "SET_NUMBER")

    def test_multiple_same_set_number_rows_are_ambiguous(self) -> None:
        rows = [
            {"setName": "SWSH07: Evolving Skies", "cardNumber": "215/203"},
            {"setName": "SWSH07: Evolving Skies", "cardNumber": "215/203"},
        ]
        self.assertEqual(match_macro_identity(self.card, rows).status, "AMBIGUOUS")

    def test_extracts_raw_and_cardmarket(self) -> None:
        row = {"prices": {"market": 100.5}, "cardmarketPrices": {"marketEur": 92.2}}
        self.assertEqual(raw_usd(row), 100.5)
        self.assertEqual(cardmarket_eur(row), 92.2)

    def test_grade_specific_count_is_not_global_total_sales(self) -> None:
        row = {
            "ebay": {
                "totalSales": 33,
                "salesByGrade": {
                    "psa10": {
                        "count": 12, "averagePrice": 34.01, "medianPrice": 34.95,
                        "lastSaleDate": "2026-07-02T00:00:00.000Z", "marketTrend": "up",
                        "smartMarketPrice": {"price": 47.49, "confidence": "high"},
                    }
                },
            }
        }
        agg = graded_aggregate(row, grader="PSA", grade=10)
        self.assertEqual(total_ebay_sales(row), 33)
        self.assertEqual(agg.sales_count, 12)
        self.assertEqual(agg.smart_market_price_usd, 47.49)

    def test_daily_grade_history_stays_aggregate_not_item_sale(self) -> None:
        row = {
            "ebay": {
                "priceHistory": {
                    "psa10": {
                        "2026-07-02": {"average": 62.495, "count": 2, "totalValue": 124.99}
                    }
                }
            }
        }
        points = daily_grade_history(row, grader="PSA", grade=10)
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].count, 2)
        self.assertEqual(points[0].average_price_usd, 62.495)


if __name__ == "__main__":
    unittest.main()
