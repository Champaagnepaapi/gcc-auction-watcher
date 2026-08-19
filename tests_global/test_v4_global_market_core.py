import unittest
from datetime import datetime, timedelta, timezone

from v4_global_market_core import (
    ACTIVE_AUCTION,
    AUCTION_SNAPSHOT_LE5,
    EBAY_GRADED_AGGREGATE,
    FIXED_ASK,
    SOLD_EXACT,
    AggregatedSoldEvidence,
    CommercialIdentity,
    PriceObservation,
    build_fair_value,
    compare_market_offers,
)


NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
FX = {"USD": 1.10, "JPY": 170.0, "CHF": 0.94}


def ident(language="ja"):
    return CommercialIdentity("Pikachu", "Pokemon 151", "173/165", language, "PSA", "10")


def aggregate(
    identity,
    *,
    source="ppt",
    central=90.0,
    sale_count=193,
    age_days=3,
    family=EBAY_GRADED_AGGREGATE,
):
    return AggregatedSoldEvidence(
        source=source,
        identity=identity,
        central=central,
        low=central * 0.9,
        high=central * 1.1,
        currency="EUR",
        observed_at=NOW,
        identity_proven=True,
        sale_count=sale_count,
        last_sale_at=NOW - timedelta(days=age_days),
        recent_90_count=min(sale_count, 90),
        correlation_family=family,
    )


class GlobalMarketCoreTests(unittest.TestCase):
    def test_recent_exact_sold_drives_fair_value_and_asks_never_enter(self):
        identity = ident()
        evidence = [
            PriceObservation("poketrace", identity, SOLD_EXACT, 100, "EUR", NOW, True, sold_at=NOW-timedelta(days=8)),
            PriceObservation("ebay", identity, SOLD_EXACT, 110, "EUR", NOW, True, sold_at=NOW-timedelta(days=20)),
            PriceObservation("fanatics", identity, FIXED_ASK, 30, "EUR", NOW, True),
        ]
        fair = build_fair_value(
            identity,
            evidence,
            now=NOW,
            currency_per_eur=FX,
            aggregate_evidence=[aggregate(identity, central=20)],
        )
        self.assertIsNotNone(fair)
        self.assertEqual(fair.central_eur, 105.0)
        self.assertEqual(fair.evidence_count, 2)
        self.assertEqual(fair.method, "RECENT_EXACT_SOLD_MEDIAN")
        self.assertTrue(fair.notification_safe)

    def test_strong_recent_exact_aggregate_can_drive_fair_value(self):
        identity = ident()
        fair = build_fair_value(
            identity,
            [],
            now=NOW,
            currency_per_eur=FX,
            aggregate_evidence=[aggregate(identity)],
        )
        self.assertIsNotNone(fair)
        self.assertEqual(fair.central_eur, 90.0)
        self.assertEqual(fair.method, "RECENT_EXACT_SOLD_AGGREGATE")
        self.assertTrue(fair.notification_safe)
        self.assertIn("not item-level SOLD", fair.note)

    def test_stale_or_weak_aggregate_cannot_create_safe_fair_value(self):
        identity = ident()
        stale = build_fair_value(
            identity,
            [],
            now=NOW,
            currency_per_eur=FX,
            aggregate_evidence=[aggregate(identity, age_days=31)],
        )
        self.assertIsNone(stale)
        weak = build_fair_value(
            identity,
            [],
            now=NOW,
            currency_per_eur=FX,
            aggregate_evidence=[aggregate(identity, sale_count=2)],
        )
        self.assertIsNotNone(weak)
        self.assertFalse(weak.notification_safe)
        self.assertEqual(weak.evidence_quality, "WEAK")

    def test_one_recent_exact_sold_plus_agreeing_aggregate_is_safe(self):
        identity = ident()
        one = PriceObservation(
            "fanatics_sold",
            identity,
            SOLD_EXACT,
            100,
            "EUR",
            NOW,
            True,
            sold_at=NOW-timedelta(days=5),
        )
        fair = build_fair_value(
            identity,
            [one],
            now=NOW,
            currency_per_eur=FX,
            aggregate_evidence=[aggregate(identity, central=95)],
        )
        self.assertIsNotNone(fair)
        self.assertEqual(fair.method, "RECENT_EXACT_SOLD_PLUS_AGGREGATE")
        self.assertTrue(fair.notification_safe)
        self.assertEqual(fair.central_eur, 97.5)

    def test_correlated_ppt_and_poketrace_are_not_double_counted(self):
        identity = ident()
        ppt = aggregate(identity, source="ppt", central=90, sale_count=193, age_days=3)
        poketrace = aggregate(identity, source="poketrace", central=120, sale_count=500, age_days=5)
        fair = build_fair_value(
            identity,
            [],
            now=NOW,
            currency_per_eur=FX,
            aggregate_evidence=[ppt, poketrace],
        )
        self.assertIsNotNone(fair)
        self.assertEqual(fair.sources, ("ppt",))
        self.assertEqual(fair.central_eur, 90.0)
        self.assertEqual(fair.correlation_families, (EBAY_GRADED_AGGREGATE,))

    def test_old_sales_require_proven_time_adjustment(self):
        identity = ident()
        weak = [
            PriceObservation("ebay", identity, SOLD_EXACT, 80+i, "EUR", NOW, True, sold_at=NOW-timedelta(days=120+i*20))
            for i in range(3)
        ]
        self.assertIsNone(build_fair_value(identity, weak, now=NOW, currency_per_eur=FX))
        adjusted = [
            PriceObservation("ebay", identity, SOLD_EXACT, 80+i, "EUR", NOW, True, sold_at=NOW-timedelta(days=120+i*20), time_adjustment_factor=1.1)
            for i in range(3)
        ]
        fair = build_fair_value(identity, adjusted, now=NOW, currency_per_eur=FX)
        self.assertIsNotNone(fair)
        self.assertEqual(fair.method, "TIME_ADJUSTED_EXACT_SOLD_MEDIAN")

    def test_cross_market_ranking_uses_all_in_and_excludes_active_auction(self):
        identity = ident()
        sold = [
            PriceObservation("ebay", identity, SOLD_EXACT, 100, "EUR", NOW, True, sold_at=NOW-timedelta(days=5)),
            PriceObservation("fanatics_sold", identity, SOLD_EXACT, 100, "EUR", NOW, True, sold_at=NOW-timedelta(days=12)),
        ]
        fair = build_fair_value(identity, sold, now=NOW, currency_per_eur=FX)
        offers = [
            PriceObservation("fanatics", identity, FIXED_ASK, 60, "EUR", NOW, True),
            PriceObservation("cardova", identity, FIXED_ASK, 11000, "JPY", NOW, True, logistics_cost=500),
            PriceObservation("magi", identity, FIXED_ASK, 12000, "JPY", NOW, True, buyer_fee_rate=0.03),
            PriceObservation("cardova-auction", identity, ACTIVE_AUCTION, 1000, "JPY", NOW, True, buyer_fee_rate=0.11),
        ]
        report = compare_market_offers(fair, offers, currency_per_eur=FX, min_discount_pct=30)
        self.assertEqual(report.best_source, "fanatics")
        active = next(x for x in report.offers if x.observation.source == "cardova-auction")
        self.assertIsNone(active.rank)
        self.assertFalse(active.notify_eligible)
        fixed = next(x for x in report.offers if x.observation.source == "fanatics")
        self.assertEqual(fixed.rank, 1)
        self.assertTrue(fixed.notify_eligible)

    def test_le5_auction_can_notify_but_is_never_sold_evidence(self):
        identity = ident()
        sold = [
            PriceObservation("ebay", identity, SOLD_EXACT, 100, "EUR", NOW, True, sold_at=NOW-timedelta(days=5)),
            PriceObservation("fanatics_sold", identity, SOLD_EXACT, 100, "EUR", NOW, True, sold_at=NOW-timedelta(days=10)),
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
