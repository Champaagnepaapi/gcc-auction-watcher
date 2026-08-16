import unittest
from datetime import datetime, timedelta, timezone

import japan_edge_hunter as japan
from v4_global_live_shadow import (
    ShadowOffer,
    SourceStatus,
    best_offer,
    build_report,
    build_seed_panel,
    global_identity,
    strict_text_identity,
)
from v4_global_market_core import ACTIVE_AUCTION, FIXED_ASK, PriceObservation

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
SOURCE_ID = japan.Identity(
    name="Pikachu",
    set_name="S-P Promotional cards",
    number="227/S-P",
    language="Japanese",
    grader="PSA",
    grade="10",
    year=2021,
)


def sales(identity=SOURCE_ID):
    return [
        japan.Sold(identity, 100.0, NOW - timedelta(days=5), "s1"),
        japan.Sold(identity, 110.0, NOW - timedelta(days=12), "s2"),
    ]


class GlobalLiveShadowTests(unittest.TestCase):
    def test_seed_panel_uses_recent_exact_solds(self):
        seeds = build_seed_panel(sales(), observed_at=NOW, max_identities=5)
        self.assertEqual(len(seeds), 1)
        self.assertEqual(seeds[0].fair_value.central_eur, 105.0)
        self.assertEqual(seeds[0].fair_value.method, "RECENT_EXACT_SOLD_MEDIAN")

    def test_strict_text_identity_requires_full_number_language_grade_set(self):
        ok, _ = strict_text_identity(
            "2021 Pokemon Japanese S-P Promotional cards #227/S-P Pikachu PSA 10 GEM MT",
            SOURCE_ID,
        )
        self.assertTrue(ok)
        missing_denominator, reason = strict_text_identity(
            "2021 Pokemon Japanese S-P Promotional cards #227 Pikachu PSA 10 GEM MT",
            SOURCE_ID,
        )
        self.assertFalse(missing_denominator)
        self.assertEqual(reason, "collector_number_unproven")
        wrong_language, reason = strict_text_identity(
            "2021 Pokemon English S-P Promotional cards #227/S-P Pikachu PSA 10 GEM MT",
            SOURCE_ID,
        )
        self.assertFalse(wrong_language)
        self.assertEqual(reason, "language_unproven")

    def test_sensitive_variant_must_be_explicit(self):
        identity = japan.Identity(
            name="Pikachu",
            set_name="Test Set",
            number="1/100",
            language="Japanese",
            grader="PSA",
            grade="10",
            year=2020,
            variety="Master Ball",
        )
        ok, reason = strict_text_identity("Japanese Test Set #1/100 Pikachu PSA 10", identity)
        self.assertFalse(ok)
        self.assertIn("sensitive_variant_unproven", reason)

    def test_active_auction_never_wins_best_offer(self):
        offers = [
            ShadowOffer("gcc", ACTIVE_AUCTION, "a", "", "", "EUR", 1, 1, 99, None, None, "RAW", ""),
            ShadowOffer("magi", FIXED_ASK, "b", "", "", "EUR", 60, 60, 40, None, None, "RAW", ""),
        ]
        market, discount, basis = best_offer(offers)
        self.assertEqual(market, "magi")
        self.assertEqual(discount, 40)
        self.assertEqual(basis, "RAW_ASK_ONLY")

    def test_proven_all_in_basis_beats_raw_only_ranking(self):
        offers = [
            ShadowOffer("magi", FIXED_ASK, "a", "", "", "EUR", 40, 40, 60, None, None, "RAW", ""),
            ShadowOffer("fanatics", FIXED_ASK, "b", "", "", "EUR", 50, 50, 50, 50, 50, "VAULT", ""),
        ]
        market, discount, basis = best_offer(offers)
        self.assertEqual(market, "fanatics")
        self.assertEqual(discount, 50)
        self.assertEqual(basis, "PROVEN_OR_DECLARED_ALL_IN_BASIS")

    def test_report_keeps_missing_market_status_explicit(self):
        seed = build_seed_panel(sales(), observed_at=NOW, max_identities=1)[0]
        offer = PriceObservation(
            source="magi",
            identity=global_identity(SOURCE_ID),
            evidence_type=FIXED_ASK,
            price=10000,
            currency="JPY",
            observed_at=NOW,
            identity_proven=True,
            buyer_fee_rate=None,
        )
        source_rows = {
            "magi": {seed.identity.strict_key: [(offer, "https://example.test", "ask")]},
            "cardova": {seed.identity.strict_key: []},
        }
        report = build_report(
            [seed],
            source_rows,
            fx={"JPY": 170.0},
            statuses=[
                SourceStatus("magi", "OK"),
                SourceStatus("cardova", "AUTH_SESSION_INPUT_REQUIRED"),
            ],
            observed_at=NOW,
        )
        self.assertEqual(report["source_status"][1]["status"], "AUTH_SESSION_INPUT_REQUIRED")
        self.assertEqual(report["cards"][0]["offers"][0]["market"], "magi")
        self.assertIsNone(report["cards"][0]["offers"][0]["all_in_eur"])


if __name__ == "__main__":
    unittest.main()
