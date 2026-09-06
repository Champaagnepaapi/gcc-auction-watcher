from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

import japan_edge_external_market as market
import japan_edge_hunter as base
import japan_edge_hunter_v3 as v3


IDENTITY = base.Identity(
    name="Alakazam ex",
    set_name="Pokemon Card 151",
    number="203/165",
    language="Japanese",
    grader="PSA",
    grade="10",
    year=2023,
)


def ask(provider: str, text: str, price: int = 10000) -> base.Ask:
    url = (
        "https://jp.mercari.com/item/m123"
        if provider == "mercari"
        else "https://snkrdunk.com/apparels/128119/used/49090623"
    )
    return base.Ask(
        provider,
        url,
        "Alakazam ex 203/165 PSA10 Japanese Pokemon Card 151",
        price,
        text,
    )


class ExternalMarketTests(unittest.TestCase):
    def test_mercari_sold_page_is_never_an_active_ask(self):
        self.assertEqual(market.listing_state(ask("mercari", "この商品は配送されました")), "SOLD_PAGE")
        ok, reason = market.strict_identity_and_availability(
            ask("mercari", "この商品は配送されました"), IDENTITY
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "marketplace_sold_page")

    def test_mercari_requires_positive_active_proof(self):
        self.assertEqual(market.listing_state(ask("mercari", "購入手続きへ 日本版")), "ACTIVE")
        self.assertEqual(market.listing_state(ask("mercari", "日本版 商品説明だけ")), "UNKNOWN")

    def test_snkrdunk_sold_and_active_are_distinct(self):
        self.assertEqual(market.listing_state(ask("snkrdunk", "SOLD OUT")), "SOLD_PAGE")
        self.assertEqual(market.listing_state(ask("snkrdunk", "Buy Now Japanese")), "ACTIVE")
        self.assertTrue(market.SNKRDUNK_PROVIDER.item_re.match("https://snkrdunk.com/apparels/128119/used/49090623"))

    def test_active_exact_mercari_identity_passes(self):
        active = ask(
            "mercari",
            "購入手続きへ 日本版 Alakazam ex Pokemon Card 151 203/165 PSA10",
        )
        ok, reason = market.strict_identity_and_availability(active, IDENTITY)
        self.assertTrue(ok, reason)

    def test_external_fair_value_not_gcc_history_drives_discount(self):
        external = v3.ExternalReference(
            status="EXACT_SOLD_CONFIRMED",
            fair_eur=100.0,
            sold_count=5,
            source="eBay SOLD family + PSA APR",
            evidence_strength="STRONG",
        )
        op = market.build_opportunity(
            ask("mercari", "購入手続きへ 日本版", 9000),
            IDENTITY,
            external,
            Decimal("180"),
            Decimal("0.95"),
            30.0,
            0,
            0.0,
        )
        self.assertIsNotNone(op)
        self.assertEqual(op.external_fair_eur, 100.0)
        self.assertEqual(op.landed_eur, 50.0)
        self.assertEqual(op.discount_pct, 50.0)
        self.assertEqual(op.evidence, "GLOBAL_EXACT_GRADED_SOLD")

    def test_external_unavailable_fails_closed(self):
        unavailable = v3.ExternalReference(status="GLOBAL_EXACT_SOLD_UNAVAILABLE")
        op = market.build_opportunity(
            ask("mercari", "購入手続きへ 日本版", 9000),
            IDENTITY,
            unavailable,
            Decimal("180"),
            Decimal("0.95"),
            30.0,
            0,
            0.0,
        )
        self.assertIsNone(op)

    def test_snkrdunk_is_not_claimed_as_direct_switzerland_delivery(self):
        self.assertIn("SWITZERLAND_DIRECT_UNSUPPORTED", market.delivery_route("snkrdunk"))
        self.assertIn("CROSSBORDER", market.delivery_route("mercari"))

    def test_identity_seed_does_not_use_sale_price_as_fair_value(self):
        sale = base.Sold(IDENTITY, 12.0, datetime(2026, 9, 1, tzinfo=timezone.utc), "sold-1")
        seeds = market.identity_seeds([sale])
        self.assertEqual(len(seeds), 1)
        self.assertFalse(hasattr(seeds[0], "fair_eur"))


if __name__ == "__main__":
    unittest.main()
