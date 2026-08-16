import unittest
from datetime import datetime, timedelta, timezone

from v4_global_market_core import (
    ACTIVE_AUCTION,
    AUCTION_SNAPSHOT_LE5,
    FIXED_ASK,
    SOLD_EXACT,
    CommercialIdentity,
    PriceObservation,
    build_fair_value,
    compare_market_offers,
)


NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
FX = {"USD": 1.10, "JPY": 170.0, "CHF": 0.94}


def ident(language="ja"):
    return CommercialIdentity("Pikachu", "Pokemon 151", "173/165", language, "PSA", "10")


class GlobalMarketCoreTests(unittest.TestCase):
    def test_recent_exact_sold_drives_fair_value_and_asks_never_enter(self):
        identity = ident()
        evidence = [
            PriceObservation("poketrace", identity, SOLD_EXACT, 100, "EUR", NOW, True, sold_at=NOW-timedelta(days=8)),
            PriceObservation("ebay", identity, SOLD_EXACT, 110, "EUR", NOW, True, sold_at=NOW-timedelta(days=20)),
            PriceObservation("fanatics", identity, FIXED_ASK, 30, "EUR", NOW, True),
        ]
        fair = build_fair_value(identity, evidence, now=NOW, currency_per_eur=FX)
        self.assertIsNotNone(fair)
        self.assertEqual(fair.central_eur, 105.0)
        self.assertEqual(fair.evidence_count, 2)
        self.assertEqual(fair.method, "RECENT_EXACT_SOLD_MEDIAN")
        self.assertTrue(fair.notification_safe)

    def test_old_sales_require_proven_time_adjustment(self):
        identity = ident()
        weak = [
            PriceObservation("ppt", identity, SOLD_EXACT, 80+i, "EUR", NOW, True, sold_at=NOW-timedelta(days=120+i*20))
            for i in range(3)
        ]
        self.assertIsNone(build_fair_value(identity, weak, now=NOW, currency_per_eur=FX))
        adjusted = [
            PriceObservation("ppt", identity, SOLD_EXACT, 80+i, "EUR", NOW, True, sold_at=NOW-timedelta(days=120+i*20), time_adjustment_factor=1.1)
            for i in range(3)
        ]
        fair = build_fair_value(identity, adjusted, now=NOW, currency_per_eur=FX)
        self.assertIsNotNone(fair)
        self.assertEqual(fair.method, "TIME_ADJUSTED_EXACT_SOLD_MEDIAN")

    def test_cross_market_ranking_uses_all_in_and_blocks_active_auction_notification(self):
        identity = ident()
        sold = [
            PriceObservation("poketrace", identity, SOLD_EXACT, 100, "EUR", NOW, True, sold_at=NOW-timedelta(days=5)),
            PriceObservation("poketrace", identity, SOLD_EXACT, 100, "EUR", NOW, True, sold_at=NOW-timedelta(days=12)),
        ]
        fair = build_fair_value(identity, sold, now=NOW, currency_per_eur=FX)
        offers = [
            PriceObservation("fanatics", identity, FIXED_ASK, 60, "EUR", NOW, True),
            PriceObservation("cardova", identity, FIXED_ASK, 11000, "JPY", NOW, True, logistics_cost=500),
            PriceObservation("magi", identity, FIXED_ASK, 12000, "JPY", NOW, True, buyer_fee_rate=0.03),
            PriceObservation("cardova-auction", identity, ACTIVE_AUCTION, 1000, "JPY", NOW, True, buyer_fee_rate=0.11),
        ]
        report = compare_market_offers(fair, offers, currency_per_eur=FX, min_discount_pct=30)
        self.assertEqual(report.best_source, "cardova-auction")
        active = next(x for x in report.offers if x.observation.source == "cardova-auction")
        self.assertFalse(active.notify_eligible)
        fixed = next(x for x in report.offers if x.observation.source == "fanatics")
        self.assertTrue(fixed.notify_eligible)

    def test_le5_auction_can_notify_but_is_never_sold_evidence(self):
        identity = ident()
        sold = [
            PriceObservation("poketrace", identity, SOLD_EXACT, 100, "EUR", NOW, True, sold_at=NOW-timedelta(days=5)),
            PriceObservation("ebay", identity, SOLD_EXACT, 100, "EUR", NOW, True, sold_at=NOW-timedelta(days=10)),
        ]
        fair = build_fair_value(identity, sold, now=NOW, currency_per_eur=FX)
        snap = PriceObservation("cardova", identity, AUCTION_SNAPSHOT_LE5, 8000, "JPY", NOW, True, buyer_fee_rate=0.11)
        report = compare_market_offers(fair, [snap], currency_per_eur=FX, min_discount_pct=30)
        self.assertTrue(report.offers[0].notify_eligible)
        self.assertFalse(snap.is_exact_sold)

    def test_french_offer_not_actionable(self):
        identity = ident("fr")
        sold = [
            PriceObservation("gcc", identity, SOLD_EXACT, 100, "EUR", NOW, True, sold_at=NOW-timedelta(days=5)),
            PriceObservation("gcc", identity, SOLD_EXACT, 100, "EUR", NOW, True, sold_at=NOW-timedelta(days=8)),
        ]
        fair = build_fair_value(identity, sold, now=NOW, currency_per_eur=FX)
        offer = PriceObservation("gcc", identity, FIXED_ASK, 40, "EUR", NOW, True)
        report = compare_market_offers(fair, [offer], currency_per_eur=FX)
        self.assertFalse(report.offers[0].notify_eligible)
        self.assertEqual(report.offers[0].reason, "LANGUAGE_NOT_ACTIONABLE")

    def test_strict_identity_does_not_mix_languages_or_variants(self):
        jp = ident("ja")
        en = ident("en")
        stamped = CommercialIdentity("Pikachu", "Pokemon 151", "173/165", "ja", "PSA", "10", variant="stamp")
        self.assertNotEqual(jp.strict_key, en.strict_key)
        self.assertNotEqual(jp.strict_key, stamped.strict_key)


if __name__ == "__main__":
    unittest.main()
