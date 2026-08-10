import json
import io
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


# Les fonctions statistiques sont testables même sur une machine où les
# dépendances réseau/navigateur n'ont pas encore été installées.
try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    sys.modules["requests"] = types.SimpleNamespace(post=None)

try:
    import dotenv  # noqa: F401
except ModuleNotFoundError:
    dotenv_module = types.ModuleType("dotenv")
    dotenv_module.load_dotenv = lambda: None
    sys.modules["dotenv"] = dotenv_module

try:
    import playwright.sync_api  # noqa: F401
except ModuleNotFoundError:
    playwright_module = types.ModuleType("playwright")
    sync_api_module = types.ModuleType("playwright.sync_api")
    sync_api_module.sync_playwright = None
    sync_api_module.TimeoutError = TimeoutError
    playwright_module.sync_api = sync_api_module
    sys.modules["playwright"] = playwright_module
    sys.modules["playwright.sync_api"] = sync_api_module

import watcher


NOW = datetime(2026, 8, 10, tzinfo=timezone.utc)


def sale(price, days_ago=10, **kwargs):
    return watcher.ComparableSale(
        price=price,
        sold_at=NOW - timedelta(days=days_ago),
        grader=kwargs.pop("grader", "PSA"),
        grade=kwargs.pop("grade", 10.0),
        **kwargs,
    )


def opportunity(minutes=30, price=42.0, max_recommended=70.0):
    lot = watcher.Lot(
        url="https://gradedcardcenter.com/item/test-opportunity",
        title="PSA 10 Otaquin",
        current_price=price,
        source_type="auction",
        minutes_to_end=minutes,
        grader="PSA",
        grade="10",
    )
    estimate = watcher.MarketEstimate(
        low=100.0,
        central=110.0,
        high=120.0,
        kept_comparables=[],
        rejected_outliers=[],
        recent_90_count=0,
        dated_count=0,
        liquidity="faible",
        dispersion="faible",
        confidence="faible",
        adaptive_discount_pct=40.0,
        rationale="test",
        source_counts={"gcc": 2},
        exact_grade_count=2,
        same_grader_count=2,
    )
    return watcher.Opportunity(
        lot=lot,
        estimate=estimate,
        discount_pct=(110.0 - price) / 110.0 * 100,
        max_recommended=max_recommended,
        gcc_comparables=[],
        ebay_comparables=[],
    )


class ParsingRegressionTests(unittest.TestCase):
    def test_impossible_grades_are_rejected_without_decimal_rewrite(self):
        watcher.LOGGED_INVALID_GRADES.clear()
        cases = (
            ("BGS 48", "BGS", "48"),
            ("CGC 50", "CGC", "50"),
            ("BGS 75", "BGS", "75"),
            ("PSA 0", "PSA", "0"),
            ("BGS -1", "BGS", "-1"),
        )
        for text, expected_grader, raw_grade in cases:
            with self.subTest(text=text):
                output = io.StringIO()
                with redirect_stdout(output):
                    grader, grade = watcher.parse_grader_grade(text)
                self.assertEqual(grader, expected_grader)
                self.assertIsNone(grade)
                self.assertIn(
                    f"grade invalide ignoré: {expected_grader} {raw_grade}",
                    output.getvalue(),
                )

    def test_real_decimal_and_ten_grades_are_accepted(self):
        self.assertEqual(watcher.parse_grader_grade("BGS 9.5"), ("BGS", "9.5"))
        self.assertEqual(watcher.parse_grader_grade("PSA 10"), ("PSA", "10"))
        self.assertEqual(
            watcher.parse_grader_grade("PSA 10 Dracaufeu Pop 282"),
            ("PSA", "10"),
        )
        self.assertEqual(
            watcher.parse_grader_grade("Grader: BGS\nPop 282\nGrade: 9.5"),
            ("BGS", "9.5"),
        )
        self.assertEqual(
            watcher.parse_grader_grade(
                "Article\nGradation\nDétails\nBGS\n9.5\nPop 282"
            ),
            ("BGS", "9.5"),
        )

    def test_population_never_becomes_grade(self):
        grader, grade = watcher.parse_grader_grade("Grader: BGS\nPopulation\nPop 282")
        self.assertEqual(grader, "BGS")
        self.assertIsNone(grade)

    def test_population_never_becomes_card_title(self):
        self.assertEqual(watcher.sanitize_card_title("Pop 15"), "")
        self.assertEqual(watcher.sanitize_card_title("Pop 282"), "")
        self.assertEqual(
            watcher.extract_card_title(
                page_heading="Pop 15",
                listing_text="Pop 15\nPSA 10\nOtaquin\n42 €",
            ),
            "Otaquin",
        )
        self.assertEqual(
            watcher.extract_card_title(
                page_heading="Pop 15",
                body="Nom de la carte: Otaquin\nPopulation: 15",
            ),
            "Otaquin",
        )

    def test_unidentified_pop_title_rejects_lot(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/pop-only",
            title="Pop 15",
            current_price=20,
            source_type="auction",
            body="Catégorie: Pokémon\nRéférence: #045/132",
        )
        with redirect_stdout(io.StringIO()):
            self.assertFalse(watcher.is_valid_pokemon_card(lot))


class TargetGradeSafetyTests(unittest.TestCase):
    def test_missing_target_grade_cannot_mix_same_grader_sales(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/bgs-missing-grade",
            title="Carte BGS au grade illisible",
            current_price=20,
            source_type="auction",
            grader="BGS",
            grade=None,
        )
        sales = [sale(50, grader="BGS", grade=8), sale(100, grader="BGS", grade=10)]
        output = io.StringIO()
        with redirect_stdout(output):
            result = watcher.estimate_with_grade(lot, sales, NOW)
        self.assertIsNone(result)
        self.assertIn("grader/grade cible non lisible", output.getvalue())

    def test_missing_grader_and_grade_returns_none(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/missing-grader-grade",
            title="Carte sans grader ni grade",
            current_price=20,
            source_type="auction",
            grader="",
            grade=None,
        )
        with redirect_stdout(io.StringIO()):
            self.assertIsNone(watcher.estimate_with_grade(lot, [sale(100)], NOW))

    def test_valid_bgs_nine_point_five_still_works(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/bgs-nine-point-five",
            title="BGS 9.5 Test",
            current_price=20,
            source_type="auction",
            grader="BGS",
            grade="9.5",
        )
        sales = [sale(price, grader="BGS", grade=9.5) for price in (50, 55, 60)]
        opportunity = watcher.estimate_with_grade(lot, sales, NOW)
        self.assertIsNotNone(opportunity)
        self.assertEqual(opportunity.estimate.central, 55)

    def test_parsed_bgs_48_cannot_create_end_to_end_opportunity(self):
        with redirect_stdout(io.StringIO()):
            grader, grade = watcher.parse_grader_grade("BGS 48")
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/bgs-48",
            title="Carte BGS au grade impossible",
            current_price=20,
            source_type="auction",
            grader=grader,
            grade=grade,
        )
        sales = [sale(50, grader="BGS", grade=8), sale(100, grader="BGS", grade=10)]
        self.assertEqual((grader, grade), ("BGS", None))
        with redirect_stdout(io.StringIO()):
            self.assertIsNone(watcher.estimate_with_grade(lot, sales, NOW))


class EstimationTests(unittest.TestCase):
    def test_recency_weights_decrease_progressively(self):
        weights = [
            watcher.recency_weight(NOW - timedelta(days=days), NOW)
            for days in (10, 60, 120, 240, 500)
        ]
        self.assertEqual(weights, sorted(weights, reverse=True))
        self.assertAlmostEqual(weights[0], 1.0)
        self.assertGreater(weights[-1], 0.0)

    def test_mad_rejects_extreme_outlier(self):
        comparables = [sale(price) for price in (95, 100, 102, 105, 310)]
        kept, rejected = watcher.filter_price_outliers(comparables)
        self.assertEqual([item.price for item in rejected], [310])
        self.assertEqual(len(kept), 4)

    def test_adaptive_threshold_follows_quality_bands(self):
        weak = watcher.adaptive_discount_threshold(2, "faible", "faible", 1, 2, 2)
        medium = watcher.adaptive_discount_threshold(4, "faible", "moyenne", 3, 4, 4)
        strong = watcher.adaptive_discount_threshold(6, "faible", "élevée", 5, 6, 6)
        self.assertGreaterEqual(weak, 40)
        self.assertEqual(medium, 35)
        self.assertEqual(strong, 30)

    def test_adaptive_threshold_penalizes_each_quality_problem(self):
        baseline = watcher.adaptive_discount_threshold(
            6, "faible", "élevée", 5, 6, 6, True
        )
        dispersed = watcher.adaptive_discount_threshold(
            6, "élevée", "élevée", 5, 6, 6, True
        )
        illiquid = watcher.adaptive_discount_threshold(
            6, "faible", "faible", 5, 6, 6, True
        )
        old = watcher.adaptive_discount_threshold(
            6, "faible", "moyenne", 0, 6, 6, True
        )
        inconsistent = watcher.adaptive_discount_threshold(
            6, "faible", "élevée", 5, 6, 6, False
        )
        self.assertGreater(dispersed, baseline)
        self.assertGreater(illiquid, baseline)
        self.assertGreater(old, baseline)
        self.assertGreater(inconsistent, baseline)
        self.assertGreaterEqual(baseline, watcher.MIN_DISCOUNT)

        capped = watcher.adaptive_discount_threshold(
            6, "élevée", "faible", 0, 6, 0, False, True
        )
        self.assertEqual(capped, 45)

    def test_confidence_uses_recency_dispersion_and_target_grader(self):
        strong = watcher.determine_confidence(
            6, 6, 6, 6, 5, 6, "faible", "élevée", True
        )
        old = watcher.determine_confidence(
            6, 6, 6, 6, 0, 6, "faible", "faible", True
        )
        dispersed = watcher.determine_confidence(
            6, 6, 6, 6, 5, 6, "élevée", "élevée", True
        )
        other_graders = watcher.determine_confidence(
            8, 8, 8, 0, 8, 8, "faible", "élevée", True, True
        )
        tiny_sample = watcher.determine_confidence(
            2, 2, 2, 2, 2, 2, "faible", "élevée", True
        )
        self.assertEqual(strong, "élevée")
        self.assertNotEqual(old, "élevée")
        self.assertNotEqual(dispersed, "élevée")
        self.assertEqual(other_graders, "faible")
        self.assertNotEqual(tiny_sample, "élevée")

    def test_end_to_end_target_grader_sale_dominates_many_other_graders(self):
        psa_lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/psa-target",
            title="PSA 10 Test",
            current_price=40,
            source_type="auction",
            grader="PSA",
            grade="10",
        )
        psa_sales = [sale(100, grader="PSA")]
        psa_sales.extend(sale(price, grader="PCA") for price in range(60, 68))
        psa_opportunity = watcher.estimate_with_grade(psa_lot, psa_sales, NOW)
        self.assertIsNotNone(psa_opportunity)
        self.assertGreater(psa_opportunity.estimate.central, 90)
        self.assertEqual(psa_opportunity.estimate.central, 100)
        self.assertEqual(psa_opportunity.estimate.confidence, "faible")

        pca_lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/pca-target",
            title="PCA 10 Test",
            current_price=25,
            source_type="auction",
            grader="PCA",
            grade="10",
        )
        pca_sales = [sale(60, grader="PCA")]
        pca_sales.extend(sale(price, grader="PSA") for price in range(95, 103))
        pca_opportunity = watcher.estimate_with_grade(pca_lot, pca_sales, NOW)
        self.assertIsNotNone(pca_opportunity)
        self.assertLess(pca_opportunity.estimate.central, 70)
        self.assertEqual(pca_opportunity.estimate.central, 60)

    def test_end_to_end_grade_arbitrage_is_eligible_without_normal_discount(self):
        lower_sales = [sale(price, grade=8) for price in (20, 20, 21)]
        affordable = watcher.Lot(
            url="https://gradedcardcenter.com/item/grade-arbitrage",
            title="PSA 9 Test",
            current_price=20,
            source_type="auction",
            grader="PSA",
            grade="9",
        )
        opportunity = watcher.estimate_with_grade(affordable, lower_sales, NOW)
        self.assertIsNotNone(opportunity)
        self.assertTrue(opportunity.grade_arbitrage)
        self.assertIn("grade arbitrage", opportunity.rationale)
        self.assertAlmostEqual(opportunity.estimate.central, 20)
        self.assertGreaterEqual(opportunity.max_recommended, 20)
        self.assertEqual(opportunity.confidence, "faible")

        too_expensive = watcher.Lot(
            url="https://gradedcardcenter.com/item/no-grade-arbitrage",
            title="PSA 9 Test",
            current_price=30,
            source_type="auction",
            grader="PSA",
            grade="9",
        )
        self.assertIsNone(watcher.estimate_with_grade(too_expensive, lower_sales, NOW))

        uncertain_identity = [
            sale(price, grade=8, exact_card=False) for price in (20, 20, 21)
        ]
        self.assertIsNone(
            watcher.estimate_with_grade(affordable, uncertain_identity, NOW)
        )

    def test_end_to_end_other_graders_cannot_create_value_without_ratio(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/pca-without-ratio",
            title="PCA 10 Test",
            current_price=50,
            source_type="auction",
            grader="PCA",
            grade="10",
        )
        psa_sales = [sale(price, grader="PSA") for price in (95, 98, 100, 102, 105)]
        self.assertIsNone(watcher.estimate_with_grade(lot, psa_sales, NOW))

    def test_exact_grade_sale_remains_primary_over_neighboring_grades(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/exact-priority",
            title="PSA 9 Test",
            current_price=15,
            source_type="auction",
            grader="PSA",
            grade="9",
        )
        sales = [sale(40, grade=9)] + [sale(price, grade=8) for price in (19, 20, 21)]
        estimate = watcher.build_market_estimate(lot, sales, NOW)
        self.assertIsNotNone(estimate)
        self.assertEqual(estimate.central, 40)
        self.assertLessEqual(estimate.low, 20)
        self.assertIn("signal principal", estimate.rationale)

    def test_inter_grader_ratio_requires_empirical_evidence(self):
        comparable = sale(80, grader="PCA")
        insufficient = watcher.EmpiricalGraderRatio(
            source_grader="PCA",
            target_grader="PSA",
            grade=10,
            target_per_source_ratio=1.25,
            sample_size=watcher.MIN_EMPIRICAL_GRADER_RATIO_SALES - 1,
            sources=("ebay",),
            measured_at=NOW,
        )
        sufficient = watcher.EmpiricalGraderRatio(
            source_grader="PCA",
            target_grader="PSA",
            grade=10,
            target_per_source_ratio=1.25,
            sample_size=watcher.MIN_EMPIRICAL_GRADER_RATIO_SALES,
            sources=("gcc", "ebay"),
            measured_at=NOW,
        )
        invalid_source = watcher.EmpiricalGraderRatio(
            source_grader="PCA",
            target_grader="PSA",
            grade=10,
            target_per_source_ratio=1.25,
            sample_size=watcher.MIN_EMPIRICAL_GRADER_RATIO_SALES,
            sources=("unknown",),
            measured_at=NOW,
        )
        self.assertIsNone(
            watcher.empirical_price_for_target_grader(comparable, "PSA", 10, [])
        )
        self.assertIsNone(
            watcher.empirical_price_for_target_grader(
                comparable, "PSA", 10, [insufficient]
            )
        )
        self.assertIsNone(
            watcher.empirical_price_for_target_grader(
                comparable, "PSA", 10, [invalid_source]
            )
        )
        self.assertEqual(
            watcher.empirical_price_for_target_grader(
                comparable, "PSA", 10, [sufficient]
            ),
            100,
        )

    def test_end_to_end_empirical_ratio_can_unlock_normalized_value(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/psa-with-ratio",
            title="PSA 10 Test",
            current_price=50,
            source_type="auction",
            grader="PSA",
            grade="10",
        )
        ratio = watcher.EmpiricalGraderRatio(
            source_grader="PCA",
            target_grader="PSA",
            grade=10,
            target_per_source_ratio=1.25,
            sample_size=watcher.MIN_EMPIRICAL_GRADER_RATIO_SALES,
            sources=("gcc", "ebay"),
            measured_at=NOW,
        )
        pca_sales = [sale(80, grader="PCA") for _ in range(5)]
        opportunity = watcher.estimate_with_grade(
            lot, pca_sales, NOW, grader_ratios=[ratio]
        )
        self.assertIsNotNone(opportunity)
        self.assertEqual(opportunity.estimate.central, 100)
        self.assertEqual(opportunity.confidence, "faible")

    def test_ebay_query_and_card_budgets_are_independent(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/ebay-budget",
            title="PSA 10 Otaquin",
            current_price=42,
            source_type="auction",
            grader="PSA",
            grade="10",
            body=(
                "Référence: #045/132\nAnnée: 2026\nLangue: Français\n"
                "Série: Mega Evolution\n"
            ),
        )
        self.assertEqual(len(watcher.ebay_queries_within_budget(lot, 1)), 1)
        self.assertGreaterEqual(len(watcher.ebay_queries_within_budget(lot, 3)), 2)
        with patch.object(watcher, "EBAY_ENABLED", True):
            self.assertTrue(watcher.ebay_card_validation_allowed(2, 3))
            self.assertFalse(watcher.ebay_card_validation_allowed(3, 3))

    def test_estimate_has_prudent_range_and_ignores_outlier(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/test",
            title="PSA 10 Otaquin #045/132",
            current_price=60,
            source_type="fixed",
            grader="PSA",
            grade="10",
        )
        estimate = watcher.build_market_estimate(
            lot, [sale(price, days_ago=index * 10) for index, price in enumerate((95, 100, 102, 105, 310))], NOW
        )
        self.assertIsNotNone(estimate)
        self.assertLessEqual(estimate.low, estimate.central)
        self.assertLessEqual(estimate.central, estimate.high)
        self.assertLess(estimate.high, 110)
        self.assertEqual(len(estimate.rejected_outliers), 1)

        op = watcher._opportunity_from_estimate(lot, estimate, [])
        expected_max = estimate.low * (1 - estimate.adaptive_discount_pct / 100)
        self.assertAlmostEqual(op.max_recommended, expected_max)

    def test_parse_french_and_relative_sale_dates(self):
        self.assertEqual(
            watcher.parse_sale_date("Vendu le 4 juin 2026", NOW).date().isoformat(),
            "2026-06-04",
        )
        self.assertEqual(
            watcher.parse_sale_date("sold 12 days ago", NOW).date().isoformat(),
            "2026-07-29",
        )

    def test_identity_extracts_reference_language_and_series(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/identity",
            title="PSA 10 Otaquin",
            current_price=42,
            source_type="fixed",
            grader="PSA",
            grade="10",
            body=(
                "Catégorie: Pokémon\nRéférence: #045/132\nAnnée: 2026\n"
                "Langue: Français\nSérie: Mega Evolution\n"
            ),
        )
        identity = watcher.extract_card_identity(lot)
        self.assertEqual(identity["ref"], "045/132")
        self.assertEqual(identity["language"], "French")
        self.assertEqual(identity["series"], "Mega Evolution")


class NotificationTests(unittest.TestCase):
    def test_grade_arbitrage_notification_is_explicit(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/grade-alert",
            title="PSA 9 Test",
            current_price=20,
            source_type="auction",
            grader="PSA",
            grade="9",
            minutes_to_end=12,
        )
        op = watcher.estimate_with_grade(
            lot, [sale(price, grade=8) for price in (20, 20, 21)], NOW
        )
        output = io.StringIO()
        with patch.object(watcher, "NTFY_TOPIC", ""), redirect_stdout(output):
            watcher.notify(
                op,
                watcher.NotificationDecision(True, False, ("nouvel arbitrage",)),
            )
        message = output.getvalue()
        self.assertIn("GCC AUCTION — ARBITRAGE GRADE", message)
        self.assertIn("Valeur exacte du grade cible : non estimée", message)
        self.assertIn("Décote classique : non applicable", message)

    def test_fixed_price_above_recommended_max_is_rejected(self):
        fixed = opportunity(minutes=None, price=42, max_recommended=40)
        fixed.lot.source_type = "fixed"
        self.assertIn("prix fixe", watcher.opportunity_rejection_reason(fixed))

    def test_auction_above_recommended_max_is_rejected(self):
        auction = opportunity(minutes=30, price=42, max_recommended=40)
        self.assertIn("enchère", watcher.opportunity_rejection_reason(auction))

    def test_auction_below_recommended_max_is_admissible(self):
        auction = opportunity(minutes=30, price=35, max_recommended=40)
        self.assertEqual(watcher.opportunity_rejection_reason(auction), "")

    def test_price_drop_and_discount_improvement_trigger(self):
        op = opportunity(minutes=30, price=42)
        previous = {"price": 50, "discount_pct": 50, "minutes_to_end": 40}
        decision = watcher.notification_decision(op, previous)
        self.assertTrue(decision.should_notify)
        self.assertIn("prix en baisse d'au moins 10%", decision.reasons)
        self.assertIn("décote améliorée d'au moins 5 points", decision.reasons)

    def test_old_state_can_trigger_single_fifteen_minute_alert(self):
        op = opportunity(minutes=12)
        old_state = {"price": 42, "discount_pct": op.discount_pct}
        first = watcher.notification_decision(op, old_state)
        self.assertTrue(first.should_notify)
        self.assertIn("passage sous 15 minutes", first.reasons)
        updated = watcher.updated_notification_state(op, old_state, first, NOW.isoformat())
        second = watcher.notification_decision(op, updated)
        self.assertFalse(second.should_notify)

    def test_final_alert_is_high_priority_and_sent_once(self):
        op = opportunity(minutes=5, price=42, max_recommended=70)
        previous = {
            "price": 42,
            "discount_pct": op.discount_pct,
            "minutes_to_end": 12,
            "alert_15m_sent": True,
            "final_alert_sent": False,
        }
        first = watcher.notification_decision(op, previous)
        self.assertTrue(first.should_notify)
        self.assertTrue(first.final_alert)
        updated = watcher.updated_notification_state(op, previous, first, NOW.isoformat())
        second = watcher.notification_decision(op, updated)
        self.assertFalse(second.should_notify)
        self.assertFalse(second.final_alert)

    def test_final_alert_requires_price_below_recommended_max(self):
        op = opportunity(minutes=4, price=75, max_recommended=70)
        previous = {
            "price": 75,
            "discount_pct": op.discount_pct,
            "minutes_to_end": 10,
            "alert_15m_sent": True,
        }
        decision = watcher.notification_decision(op, previous)
        self.assertFalse(decision.final_alert)


class StateCompatibilityTests(unittest.TestCase):
    def test_load_state_preserves_v1_entries(self):
        old_file = watcher.STATE_FILE
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "state.json"
                path.write_text(
                    json.dumps({"notified": {"url": {"price": 42}}, "seen": {}}),
                    encoding="utf-8",
                )
                watcher.STATE_FILE = path
                state = watcher.load_state()
                self.assertEqual(state["notified"]["url"]["price"], 42)
                self.assertEqual(state["schema_version"], 2)
        finally:
            watcher.STATE_FILE = old_file


if __name__ == "__main__":
    unittest.main()
