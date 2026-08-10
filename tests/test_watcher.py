import json
import io
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch


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
FIXTURES = Path(__file__).parent / "fixtures"


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


def apr_ready_opportunity():
    op = opportunity(price=42.0, max_recommended=70.0)
    op.lot.body = (
        "Catégorie: Pokémon\nRéférence: #045/132\nAnnée: 2026\n"
        "Langue: Français\nSérie: Mega Evolution\n"
    )
    op.gcc_comparables = [sale(price) for price in (100, 110, 120)]
    return op


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


class UnreadableGradeDiagnosticsTests(unittest.TestCase):
    def unreadable_lot(self, **kwargs):
        return watcher.Lot(
            url=kwargs.pop(
                "url", "https://gradedcardcenter.com/item/unreadable-grade"
            ),
            title=kwargs.pop("title", "Mimiqui"),
            current_price=kwargs.pop("current_price", 20.0),
            source_type=kwargs.pop("source_type", "fixed"),
            grader=kwargs.pop("grader", "BGS"),
            grade=kwargs.pop("grade", None),
            **kwargs,
        )

    def test_invalid_grade_diagnostic_contains_requested_raw_context(self):
        lot = self.unreadable_lot(
            page_title_raw="Mimiqui BGS 48",
            body=(
                "Mimiqui\nArticle Gradation Détails\n"
                "Société de gradation: BGS\nGrade: 48\n"
                "Certification: 12345678\nPopulation: 15\n"
                "Authorization: Bearer NE_JAMAIS_AFFICHER"
            ),
        )
        diagnostic = watcher.diagnose_unreadable_grade(lot)
        formatted = watcher.format_unreadable_grade_diagnostic(diagnostic)

        self.assertEqual(
            diagnostic.reason, watcher.GRADE_UNREADABLE_GRADE_INVALID
        )
        self.assertIn("=== DIAG GRADE ILLISIBLE ===", formatted)
        self.assertIn("Titre brut de la page: Mimiqui BGS 48", formatted)
        self.assertIn("Société de gradation: BGS", formatted)
        self.assertIn("Grade: 48", formatted)
        self.assertIn("Certification: 12345678", formatted)
        self.assertIn("Motif: grade présent mais invalide", formatted)
        self.assertNotIn("NE_JAMAIS_AFFICHER", formatted)
        self.assertNotIn("Bearer", formatted)

    def test_all_unreadable_grade_reasons_are_distinguished(self):
        cases = (
            (
                self.unreadable_lot(grader="", body="Catégorie: Pokémon"),
                watcher.GRADE_UNREADABLE_GRADER_ABSENT,
            ),
            (
                self.unreadable_lot(body="Société de gradation: BGS"),
                watcher.GRADE_UNREADABLE_GRADE_ABSENT,
            ),
            (
                self.unreadable_lot(
                    title="Mimiqui BGS 48", body="Article Gradation\nBGS 48"
                ),
                watcher.GRADE_UNREADABLE_GRADE_INVALID,
            ),
            (
                self.unreadable_lot(body="Grader: BGS\nGrade: 9\nNote: 9.5"),
                watcher.GRADE_UNREADABLE_CONFLICT,
            ),
            (
                self.unreadable_lot(
                    body=(
                        "Article Gradation Détails\nBGS\nSurface\n"
                        "Centres\n9.5"
                    )
                ),
                watcher.GRADE_UNREADABLE_AMBIGUOUS,
            ),
            (
                self.unreadable_lot(grader="XYZ", body="Grader: XYZ"),
                watcher.GRADE_UNREADABLE_OTHER,
            ),
        )
        for lot, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(
                    watcher.diagnose_unreadable_grade(lot).reason, expected
                )

    def test_item_grading_block_is_preferred_over_navigation_label(self):
        lot = self.unreadable_lot(
            title="Mimiqui BGS 48",
            body=(
                "Gradation\nVends tes articles\nMimiqui BGS 48\n"
                "Historique des ventes\nBGS 9 Mimiqui\n"
                "Description\nArticle\nGradation\nDétails\n"
                "Personnage\nMimiqui\nCatégorie\nPokemon"
            ),
        )
        diagnostic = watcher.diagnose_unreadable_grade(lot)
        self.assertIn("Article\nGradation\nDétails", diagnostic.grading_block_raw)
        self.assertNotIn("Vends tes articles", diagnostic.grading_block_raw)
        self.assertEqual(
            diagnostic.reason, watcher.GRADE_UNREADABLE_GRADE_INVALID
        )

    def test_explicit_non_numeric_grading_qualifiers_are_excluded(self):
        cases = (
            ("Grade: OC", "OC / Off Center"),
            ("Note: Off Center", "OC / Off Center"),
            ("Grade: miscut", "Miscut"),
            ("BGS ERROR Pikachu", "Error"),
            ("Qualifier: Print Defect", "Print Defect"),
        )
        for raw, expected_qualifier in cases:
            with self.subTest(raw=raw):
                lot = self.unreadable_lot(body=f"Grader: BGS\n{raw}")
                diagnostic = watcher.diagnose_unreadable_grade(lot)
                self.assertEqual(
                    diagnostic.reason, watcher.GRADE_SPECIAL_QUALIFIER
                )
                self.assertEqual(
                    diagnostic.special_qualifier, expected_qualifier
                )

    def test_special_qualifier_is_rejected_without_economic_valuation(self):
        lot = self.unreadable_lot(
            url="https://gcc.test/item/psa-oc",
            title="PSA OC Pikachu",
            grader="PSA",
            body="Article Gradation Détails\nGrader: PSA\nGrade: OC",
        )
        sales = [sale(100), sale(110), sale(120)]
        diagnostics = watcher.RunDiagnostics()
        output = io.StringIO()

        with redirect_stdout(output):
            result = watcher.estimate_with_grade(
                lot, sales, NOW, run_diagnostics=diagnostics
            )

        self.assertIsNone(result)
        self.assertEqual(
            diagnostics.rejection_count(watcher.REJECTION_SPECIAL_QUALIFIER),
            1,
        )
        self.assertEqual(
            diagnostics.rejection_count(watcher.REJECTION_GRADER_GRADE), 0
        )
        self.assertEqual(len(diagnostics.unreadable_grade_lots), 0)
        self.assertEqual(len(diagnostics.special_qualifier_lots), 1)
        self.assertIn("=== DIAG QUALIFIER SPÉCIAL EXCLU ===", output.getvalue())
        self.assertIn("Rejet valeur: PSA OC Pikachu | qualifier spécial exclu", output.getvalue())

        summary = watcher.format_run_diagnostics(diagnostics)
        self.assertIn("- grader/grade illisible: 0", summary)
        self.assertIn("- qualifier spécial exclu: 1", summary)
        self.assertIn("Nombre de lots qualifier spécial exclu: 1", summary)

    def test_error_word_outside_grading_value_is_not_a_qualifier(self):
        lot = self.unreadable_lot(
            title="Error Pikachu",
            body=(
                "Société de gradation: BGS\n"
                "Description: Error card edition"
            ),
        )
        diagnostic = watcher.diagnose_unreadable_grade(lot)
        self.assertEqual(
            diagnostic.reason, watcher.GRADE_UNREADABLE_GRADE_ABSENT
        )
        self.assertEqual(diagnostic.special_qualifier, "")

    def test_rejected_lot_is_logged_and_recorded_once_without_value_change(self):
        lot = self.unreadable_lot(
            title="Mimiqui BGS 48",
            body="Article Gradation Détails\nGrader: BGS\nGrade: 48",
        )
        sales = [sale(50, grader="BGS", grade=8), sale(100, grader="BGS")]
        diagnostics = watcher.RunDiagnostics()
        output = io.StringIO()

        with redirect_stdout(output):
            first = watcher.estimate_with_grade(
                lot, sales, NOW, run_diagnostics=diagnostics
            )
            second = watcher.estimate_with_grade(
                lot, sales, NOW, run_diagnostics=diagnostics
            )

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(
            diagnostics.rejection_count(watcher.REJECTION_GRADER_GRADE), 1
        )
        self.assertEqual(len(diagnostics.unreadable_grade_lots), 1)
        self.assertEqual(
            output.getvalue().count("=== DIAG GRADE ILLISIBLE ==="), 2
        )

    def test_run_summary_lists_each_unreadable_lot_with_reason(self):
        diagnostics = watcher.RunDiagnostics()
        first = self.unreadable_lot(url="https://gcc.test/item/one")
        second = self.unreadable_lot(
            url="https://gcc.test/item/two",
            title="Zorua",
            body="BGS 48",
        )
        for lot in (first, second):
            detail = watcher.diagnose_unreadable_grade(lot)
            diagnostics.record_unreadable_grade(lot, detail)
            diagnostics.record_valuation(lot, watcher.REJECTION_GRADER_GRADE)

        summary = watcher.format_run_diagnostics(diagnostics)
        self.assertIn("Nombre de lots grade illisible: 2", summary)
        self.assertIn(
            "https://gcc.test/item/one | Mimiqui | motif: "
            "grader reconnu mais grade absent",
            summary,
        )
        self.assertIn(
            "https://gcc.test/item/two | Zorua | motif: "
            "grade présent mais invalide",
            summary,
        )
        self.assertTrue(diagnostics.is_coherent)


class PsaAprParsingTests(unittest.TestCase):
    def setUp(self):
        self.lot = apr_ready_opportunity().lot

    def test_psa_identity_and_strong_reference_matching(self):
        snippet = (
            "2026 POKEMON MEGA EVOLUTION\nNo. 045\nOtaquin\nLanguage: French"
        )
        identity = watcher.extract_psa_apr_identity(snippet)
        self.assertEqual(identity["ref"], "045")
        self.assertEqual(identity["year"], "2026")
        self.assertEqual(identity["series"], "2026 POKEMON MEGA EVOLUTION")
        self.assertEqual(identity["core"], "Otaquin")
        score, reason = watcher.psa_apr_match_score(self.lot, snippet)
        self.assertGreaterEqual(score, watcher.PSA_APR_MATCH_MIN_SCORE)
        self.assertIn("référence exacte", reason)
        self.assertIn("année", reason)
        self.assertIn("série", reason)

    def test_wrong_card_number_is_rejected(self):
        wrong = "2026 POKEMON MEGA EVOLUTION\nNo. 046\nOtaquin"
        score, reason = watcher.psa_apr_match_score(self.lot, wrong)
        self.assertEqual(score, 0)
        self.assertEqual(reason, "mauvaise référence")

    def test_ambiguous_strong_matches_are_rejected(self):
        text = "2026 POKEMON MEGA EVOLUTION\nNo. 045\nOtaquin\nFrench"
        candidate, score, reason = watcher.choose_psa_apr_candidate(
            self.lot,
            [
                watcher.PsaAprCandidate("https://psa.test/item/one", text),
                watcher.PsaAprCandidate("https://psa.test/item/two", text),
            ],
        )
        self.assertIsNone(candidate)
        self.assertGreaterEqual(score, watcher.PSA_APR_MATCH_MIN_SCORE)
        self.assertEqual(reason, "résultats APR ambigus")

    def test_individual_sales_are_converted_separated_and_deduplicated(self):
        rows = (FIXTURES / "psa_apr_detail.txt").read_text(encoding="utf-8").splitlines()
        data = watcher.parse_psa_apr_page(rows, 10.0, 1.20, NOW)
        exact_ten = [item for item in data.sales if item.grade == 10]
        grade_nine = [item for item in data.sales if item.grade == 9]
        self.assertEqual(len(data.sales), 3)
        self.assertEqual(len(exact_ten), 2)
        self.assertEqual(len(grade_nine), 1)
        self.assertAlmostEqual(exact_ten[0].price, 93.92)
        self.assertEqual(exact_ten[0].sold_at.date().isoformat(), "2026-08-02")
        self.assertEqual(exact_ten[0].source, "psa")
        self.assertTrue(exact_ten[0].exact_card)
        self.assertEqual(exact_ten[0].match_score, 100)
        self.assertIn("cert 12345678", exact_ten[0].context)
        self.assertEqual(data.population, 523)
        self.assertEqual(data.pop_higher, 0)
        self.assertEqual(data.most_recent_price, 100.0)

    def test_usd_price_parser_and_conversion_formula(self):
        self.assertEqual(watcher.parse_psa_apr_usd("Price $1,299.50"), 1299.50)
        self.assertIsNone(watcher.parse_psa_apr_usd("Price unavailable"))
        self.assertEqual(watcher.usd_to_eur(100, 1.25), 80.0)

    def test_sale_without_price_or_grade_is_ignored(self):
        rows = [
            "May 1, 2026 | eBay | Auction | 99887766 | 10",
            "Apr 2, 2026 | eBay | Auction | 88776655 | $99.00",
        ]
        self.assertEqual(watcher.parse_psa_apr_sales(rows, 1.20, NOW), [])


class PsaAprExchangeRateTests(unittest.TestCase):
    ECB_XML = (
        '<?xml version="1.0"?><gesmes:Envelope '
        'xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" '
        'xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">'
        '<Cube><Cube time="2026-08-07"><Cube currency="USD" rate="1.2000"/>'
        '</Cube></Cube></gesmes:Envelope>'
    )

    def test_ecb_rate_is_parsed_and_fetched_only_once(self):
        response = Mock(text=self.ECB_XML)
        response.raise_for_status.return_value = None
        getter = Mock(return_value=response)
        with (
            patch.object(watcher, "_PSA_APR_RATE_LOOKUP_DONE", False),
            patch.object(watcher, "_PSA_APR_USD_PER_EUR", None),
            patch.object(watcher, "PSA_APR_USD_PER_EUR_FALLBACK", ""),
        ):
            self.assertEqual(watcher.get_psa_apr_usd_per_eur(getter), 1.2)
            self.assertEqual(watcher.get_psa_apr_usd_per_eur(getter), 1.2)
        getter.assert_called_once()

    def test_explicit_fallback_is_used_when_ecb_fails(self):
        getter = Mock(side_effect=RuntimeError("ECB down"))
        with (
            patch.object(watcher, "_PSA_APR_RATE_LOOKUP_DONE", False),
            patch.object(watcher, "_PSA_APR_USD_PER_EUR", None),
            patch.object(watcher, "PSA_APR_USD_PER_EUR_FALLBACK", "1.25"),
        ):
            self.assertEqual(watcher.get_psa_apr_usd_per_eur(getter), 1.25)

    def test_no_ecb_or_fallback_disables_apr_without_navigation(self):
        page = Mock()
        output = io.StringIO()
        with (
            patch.object(watcher, "_PSA_APR_RATE_LOOKUP_DONE", False),
            patch.object(watcher, "_PSA_APR_USD_PER_EUR", None),
            patch.object(watcher, "PSA_APR_USD_PER_EUR_FALLBACK", ""),
            patch.object(watcher, "PSA_APR_ENABLED", True),
            redirect_stdout(output),
        ):
            rate = watcher.get_psa_apr_usd_per_eur(
                Mock(side_effect=RuntimeError("ECB down"))
            )
            data = watcher.scrape_psa_apr(page, apr_ready_opportunity().lot)
        self.assertIsNone(rate)
        self.assertEqual(data.sales, [])
        page.goto.assert_not_called()
        self.assertIn(
            "PSA APR: conversion USD/EUR indisponible -> validation APR ignorée",
            output.getvalue(),
        )


class PsaAprValidationTests(unittest.TestCase):
    def test_sufficient_apr_builds_an_independent_estimate(self):
        op = apr_ready_opportunity()
        data = watcher.PsaAprData(
            sales=[
                sale(100, source="psa", grade=10),
                sale(102, source="psa", grade=10),
                sale(85, source="psa", grade=9),
            ],
            population=523,
            pop_higher=0,
            most_recent_price=100,
        )
        with patch.object(watcher, "scrape_psa_apr", return_value=data):
            result = watcher.validate_with_psa_apr(Mock(), op, now=NOW)
        self.assertTrue(result.sufficient)
        self.assertIsNotNone(result.opportunity)
        self.assertIsNotNone(result.opportunity.psa_apr_estimate)
        self.assertEqual(result.opportunity.psa_apr_estimate.central, 101)
        self.assertEqual(
            watcher._exact_count(op.lot, result.opportunity.psa_apr_comparables),
            2,
        )
        self.assertLessEqual(result.opportunity.estimate.central, op.estimate.central)

    def test_insufficient_apr_falls_back_to_ebay(self):
        op = apr_ready_opportunity()
        apr_validator = Mock(
            return_value=watcher.PsaAprValidationResult(op, False)
        )
        ebay_validator = Mock(return_value=op)
        budgets = watcher.ValidationBudgets()
        with (
            patch.object(watcher, "PSA_APR_ENABLED", True),
            patch.object(watcher, "EBAY_ENABLED", True),
        ):
            result = watcher.validate_secondary_sources(
                Mock(), op, budgets, apr_validator=apr_validator,
                ebay_validator=ebay_validator,
            )
        self.assertIs(result, op)
        apr_validator.assert_called_once()
        ebay_validator.assert_called_once()

    def test_sufficient_apr_skips_public_ebay(self):
        op = apr_ready_opportunity()
        apr_validator = Mock(
            return_value=watcher.PsaAprValidationResult(op, True)
        )
        ebay_validator = Mock(return_value=op)
        with (
            patch.object(watcher, "PSA_APR_ENABLED", True),
            patch.object(watcher, "EBAY_ENABLED", True),
        ):
            result = watcher.validate_secondary_sources(
                Mock(), op, watcher.ValidationBudgets(),
                apr_validator=apr_validator, ebay_validator=ebay_validator,
            )
        self.assertIs(result, op)
        apr_validator.assert_called_once()
        ebay_validator.assert_not_called()

    def test_non_psa_never_calls_apr(self):
        op = apr_ready_opportunity()
        op.lot.grader = "BGS"
        op.lot.grade = "9.5"
        apr_validator = Mock()
        ebay_validator = Mock(return_value=op)
        with (
            patch.object(watcher, "PSA_APR_ENABLED", True),
            patch.object(watcher, "EBAY_ENABLED", True),
        ):
            result = watcher.validate_secondary_sources(
                Mock(), op, watcher.ValidationBudgets(),
                apr_validator=apr_validator, ebay_validator=ebay_validator,
            )
        self.assertIs(result, op)
        apr_validator.assert_not_called()
        ebay_validator.assert_called_once()

    def test_apr_failure_does_not_break_scan_and_uses_ebay(self):
        op = apr_ready_opportunity()
        apr_validator = Mock(side_effect=RuntimeError("PSA down"))
        ebay_validator = Mock(return_value=op)
        with (
            patch.object(watcher, "PSA_APR_ENABLED", True),
            patch.object(watcher, "EBAY_ENABLED", True),
            redirect_stdout(io.StringIO()),
        ):
            result = watcher.validate_secondary_sources(
                Mock(), op, watcher.ValidationBudgets(),
                apr_validator=apr_validator, ebay_validator=ebay_validator,
            )
        self.assertIs(result, op)
        ebay_validator.assert_called_once()

    def test_gcc_opportunity_is_unchanged_when_validators_are_disabled(self):
        lot = apr_ready_opportunity().lot
        gcc_sales = [sale(price) for price in (95, 100, 105)]
        op = watcher.estimate_with_grade(lot, gcc_sales, NOW)
        before = (op.estimated_market, op.max_recommended, op.discount_pct)
        with (
            patch.object(watcher, "PSA_APR_ENABLED", False),
            patch.object(watcher, "EBAY_ENABLED", False),
        ):
            result = watcher.validate_secondary_sources(
                Mock(), op, watcher.ValidationBudgets()
            )
        self.assertIs(result, op)
        self.assertEqual(
            (result.estimated_market, result.max_recommended, result.discount_pct),
            before,
        )


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
    def test_psa_apr_notification_shows_real_sales_and_population(self):
        op = apr_ready_opportunity()
        apr_sales = [
            sale(98, days_ago=8, source="psa", grade=10),
            sale(100, days_ago=20, source="psa", grade=10),
        ]
        op.psa_apr_comparables = apr_sales
        op.psa_apr_estimate = watcher.build_market_estimate(op.lot, apr_sales, NOW)
        op.psa_apr_population = 523
        op.psa_apr_pop_higher = 0
        op.psa_apr_most_recent_price = 99
        op.psa_apr_note = "PSA APR cohérent"
        output = io.StringIO()
        with patch.object(watcher, "NTFY_TOPIC", ""), redirect_stdout(output):
            watcher.notify(
                op, watcher.NotificationDecision(True, False, ("nouvelle opportunité",))
            )
        message = output.getvalue()
        self.assertIn("PSA APR : 2 vente(s) PSA 10", message)
        self.assertIn("APR valeur :", message)
        self.assertIn("APR centrale :", message)
        self.assertIn("Dernière vente APR : 98.00 € — 02.08.2026", message)
        self.assertIn("Population PSA 10 : 523", message)
        self.assertIn("Pop Higher : 0", message)
        self.assertIn("Most Recent Price PSA : 99.00 €", message)

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


class GccDiagnosticsTests(unittest.TestCase):
    def diagnostic_lot(self, **kwargs):
        return watcher.Lot(
            url=kwargs.pop("url", "https://gradedcardcenter.com/item/diag"),
            title=kwargs.pop("title", "PSA 10 Diagnostic"),
            current_price=kwargs.pop("current_price", 20.0),
            source_type=kwargs.pop("source_type", "auction"),
            grader=kwargs.pop("grader", "PSA"),
            grade=kwargs.pop("grade", "10"),
            **kwargs,
        )

    def test_diagnostics_never_change_opportunity_or_market_estimate(self):
        lot = self.diagnostic_lot()
        sales = [sale(90), sale(100), sale(110)]
        baseline_estimate = watcher.build_market_estimate(lot, sales, NOW)
        diagnostics = watcher.diagnose_gcc_comparables(
            lot, sales, baseline_estimate, NOW
        )
        estimate_after_diagnostics = watcher.build_market_estimate(lot, sales, NOW)
        self.assertEqual(baseline_estimate, estimate_after_diagnostics)
        self.assertEqual(diagnostics.kept_count, 3)

        with redirect_stdout(io.StringIO()):
            baseline_opportunity = watcher.estimate_with_grade(lot, sales, NOW)
            run_diagnostics = watcher.RunDiagnostics()
            instrumented_opportunity = watcher.estimate_with_grade(
                lot, sales, NOW, run_diagnostics=run_diagnostics
            )
        self.assertEqual(baseline_opportunity, instrumented_opportunity)
        self.assertEqual(run_diagnostics.gcc_opportunities, 1)

    def test_six_sales_without_exact_grade_explain_the_rejection(self):
        lot = self.diagnostic_lot(
            title="PCA 10 Mimiqui",
            current_price=50.0,
            grader="PCA",
        )
        sales = [
            sale(30, grader="PCA", grade=9.0),
            sale(31, grader="PCA", grade=9.0),
            sale(32, grader="PCA", grade=9.0),
            sale(90, grader="PSA", grade=10.0),
            sale(100, grader="PSA", grade=10.0),
            sale(110, grader="PSA", grade=10.0),
        ]
        diagnostics = watcher.diagnose_gcc_comparables(lot, sales, now=NOW)
        self.assertEqual(diagnostics.raw_count, 6)
        self.assertEqual(diagnostics.identity_count, 6)
        self.assertEqual(diagnostics.same_grader_count, 3)
        self.assertEqual(diagnostics.exact_grade_count, 0)
        self.assertEqual(diagnostics.lower_grade_count, 3)
        self.assertEqual(diagnostics.inter_grader_candidates, 3)
        self.assertEqual(diagnostics.normalized_count, 0)
        self.assertEqual(diagnostics.ratio_rejected_count, 3)

        output = io.StringIO()
        run_diagnostics = watcher.RunDiagnostics()
        with redirect_stdout(output):
            result = watcher.estimate_with_grade(
                lot, sales, NOW, run_diagnostics=run_diagnostics
            )
        self.assertIsNone(result)
        self.assertIn("brut 6", output.getvalue())
        self.assertIn("grade exact 0", output.getvalue())
        self.assertIn("aucun comparable exact/normalisable", output.getvalue())
        self.assertEqual(
            run_diagnostics.rejection_count(
                watcher.REJECTION_INSUFFICIENT_COMPARABLES
            ),
            1,
        )

    def test_rejected_outlier_is_counted(self):
        lot = self.diagnostic_lot()
        sales = [sale(99), sale(100), sale(101), sale(1000)]
        estimate = watcher.build_market_estimate(lot, sales, NOW)
        diagnostics = watcher.diagnose_gcc_comparables(
            lot, sales, estimate, NOW
        )
        self.assertIsNotNone(estimate)
        self.assertEqual(diagnostics.outlier_count, 1)
        self.assertEqual(diagnostics.kept_count, 3)
        self.assertEqual(diagnostics.dated_count, 3)

    def test_invalid_sale_fields_and_identity_rejections_are_explained(self):
        lot = self.diagnostic_lot()
        sales = [
            sale(90, grader="", grade=10.0),
            sale(100, grader="PSA", grade=None),
            sale(110, grader="PSA", grade=10.0, exact_card=False),
        ]
        diagnostics = watcher.diagnose_gcc_comparables(lot, sales, now=NOW)
        self.assertEqual(diagnostics.raw_count, 3)
        self.assertEqual(diagnostics.identity_count, 2)
        self.assertEqual(diagnostics.invalid_grader_count, 1)
        self.assertEqual(diagnostics.invalid_grade_count, 1)
        self.assertEqual(diagnostics.insufficient_identity_count, 1)

    def test_kept_comparable_dates_are_split_into_real_age_buckets(self):
        lot = self.diagnostic_lot()
        sales = [
            sale(100, days_ago=10),
            sale(101, days_ago=60),
            sale(102, days_ago=120),
            watcher.ComparableSale(
                price=103,
                source="gcc",
                grader="PSA",
                grade=10.0,
                sold_at=None,
            ),
        ]
        estimate = watcher.build_market_estimate(lot, sales, NOW)
        diagnostics = watcher.diagnose_gcc_comparables(
            lot, sales, estimate, NOW
        )
        self.assertEqual(diagnostics.kept_count, 4)
        self.assertEqual(diagnostics.dated_count, 3)
        self.assertEqual(diagnostics.under_30_days_count, 1)
        self.assertEqual(diagnostics.days_30_to_90_count, 1)
        self.assertEqual(diagnostics.over_90_days_count, 1)

    def test_primary_rejection_reason_is_counted_once(self):
        lot = self.diagnostic_lot()
        diagnostics = watcher.RunDiagnostics()
        diagnostics.record_valuation(lot, watcher.REJECTION_EMPTY_HISTORY)
        diagnostics.record_valuation(lot, watcher.REJECTION_OTHER)
        self.assertEqual(diagnostics.lots_analyzed, 1)
        self.assertEqual(
            diagnostics.rejection_count(watcher.REJECTION_EMPTY_HISTORY), 1
        )
        self.assertEqual(diagnostics.rejection_count(watcher.REJECTION_OTHER), 0)
        self.assertTrue(diagnostics.is_coherent)

    def test_global_run_summary_is_coherent(self):
        diagnostics = watcher.RunDiagnostics(fixed_candidates=4)
        diagnostics.record_live_sales(["sale-1", "sale-2"])
        auction_lot = self.diagnostic_lot(url="auction-1")
        diagnostics.record_ending_sale("sale-1", [auction_lot])
        diagnostics.auction_candidates_ending_soon = 1
        diagnostics.record_valuation(
            self.diagnostic_lot(url="fixed-1", source_type="fixed"),
            watcher.REJECTION_EMPTY_HISTORY,
        )
        diagnostics.record_valuation(
            self.diagnostic_lot(url="fixed-2", source_type="fixed"),
            watcher.REJECTION_INSUFFICIENT_COMPARABLES,
        )
        diagnostics.record_valuation(
            self.diagnostic_lot(url="auction-2"),
            watcher.REJECTION_INSUFFICIENT_DISCOUNT,
        )
        successful = self.diagnostic_lot(url="auction-3")
        diagnostics.record_valuation(successful)
        diagnostics.record_external_rejection(successful)
        diagnostics.final_opportunities = 0

        summary = watcher.format_run_diagnostics(diagnostics)
        self.assertTrue(diagnostics.is_coherent)
        self.assertEqual(diagnostics.lots_analyzed, 4)
        self.assertEqual(diagnostics.rejected_total, 3)
        self.assertEqual(diagnostics.gcc_opportunities, 1)
        self.assertIn("Ventes live GCC: 2", summary)
        self.assertIn("Ventes terminant <=60 min: 1", summary)
        self.assertIn("Lots réellement analysés: 2", summary)
        self.assertIn("Rejetées validation externe: 1", summary)

    def test_main_workflow_serializes_scans_without_removing_schedule(self):
        workflow = (
            Path(__file__).parents[1] / ".github" / "workflows" / "watcher.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("group: gcc-auction-watcher", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn('cron: "3,13,23,33,43,53 * * * *"', workflow)


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
