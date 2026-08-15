from __future__ import annotations

import unittest

from v5 import source_scout_ebay_asp_search_probe as probe


class EbayAspSearchProbeTests(unittest.TestCase):
    def test_endpoint_and_budget_are_bounded(self) -> None:
        self.assertTrue(probe.URL.endswith("/search"))
        self.assertEqual(probe.CALL_CAP, 8)
        self.assertEqual(probe.MIN_REMAINING, 35)
        self.assertEqual(set(probe.SITES), {"US", "UK"})

    def test_panel_has_old_and_new_liquid_sentinels(self) -> None:
        ids = {card["tcgdex_id"] for card in probe.CARDS}
        self.assertEqual(ids, {"swsh7-215", "swsh8-271", "swsh12-186", "swsh7-192"})

    def test_auction_price_confidence(self) -> None:
        self.assertEqual(
            probe.price_confidence({"buying_format": "Auction"}),
            "PROVIDER_REPORTED_SOLD_STRONG_AUCTION",
        )

    def test_buy_it_now_price_confidence(self) -> None:
        self.assertEqual(
            probe.price_confidence({"buying_format": "Buy It Now"}),
            "PROVIDER_REPORTED_SOLD_STRONG_BIN",
        )

    def test_best_offer_is_not_treated_as_proven_exact_price(self) -> None:
        self.assertEqual(
            probe.price_confidence({"buying_format": "Best Offer"}),
            "PROVIDER_REPORTED_SOLD_BEST_OFFER_PRICE_UNVERIFIED",
        )

    def test_matching_keeps_signed_cards_out(self) -> None:
        card = probe.CARDS[1]
        self.assertFalse(
            probe.strict_card_match(
                card,
                {"title": "Gengar VMAX 271/264 PSA 10 Signed AUTO 10"},
            )
        )


if __name__ == "__main__":
    unittest.main()
