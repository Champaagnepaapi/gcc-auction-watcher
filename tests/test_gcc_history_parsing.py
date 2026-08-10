import unittest
import io
from contextlib import redirect_stdout

import watcher
from gcc_history_shared import (
    NON_GRADE_CHART,
    NON_GRADE_COUNTER,
    NON_GRADE_DATE,
    NON_GRADE_OTHER,
    NON_GRADE_PRICE,
    HistoricalParsingDiagnostics,
    parse_historical_grade,
)


class StrictHistoricalGradeParsingTests(unittest.TestCase):
    def test_money_parser_never_joins_grade_line_to_price_line(self):
        matches = list(watcher.MONEY_RE.finditer("PSA 10\n100 €"))
        self.assertEqual([match.group(1) for match in matches], ["100"])

    def test_case_a_psa_nine_is_not_sale_price_one_hundred(self):
        value = parse_historical_grade("PSA 9\nVente 100 €")
        self.assertEqual((value.grader, value.grade), ("PSA", "9"))
        self.assertIn(NON_GRADE_PRICE, value.rejected_numeric_kinds)

    def test_case_b_pca_decimal_is_not_sale_price_twenty(self):
        value = parse_historical_grade("PCA 9.5\nVente 20 €")
        self.assertEqual((value.grader, value.grade), ("PCA", "9.5"))

    def test_case_c_ca_ten_is_not_counter_fifty(self):
        value = parse_historical_grade("CA 10\nNombre de ventes: 50")
        self.assertEqual((value.grader, value.grade), ("CA", "10"))
        self.assertIn(NON_GRADE_COUNTER, value.rejected_numeric_kinds)

    def test_case_d_price_without_real_grade_stays_unknown(self):
        value = parse_historical_grade("Prix PCA 100 €")
        self.assertEqual(value.grader, "PCA")
        self.assertIsNone(value.grade)
        self.assertTrue(value.grade_absent)
        self.assertEqual(value.invalid_over_ten_tokens, 1)

    def test_v4_listing_parser_rejects_price_semantics_before_range_guard(self):
        output = io.StringIO()
        with redirect_stdout(output):
            parsed = watcher.parse_grader_grade("PCA 20 €")
        self.assertEqual(parsed, ("PCA", None))
        self.assertNotIn("grade invalide ignoré", output.getvalue())

    def test_unlabelled_out_of_range_number_is_other_numeric(self):
        value = parse_historical_grade("PCA 48")
        self.assertIsNone(value.grade)
        self.assertIn(NON_GRADE_OTHER, value.rejected_numeric_kinds)

    def test_case_e_special_qualifier_is_not_numeric_market(self):
        value = parse_historical_grade("Grader: PCA\nNote: OC\n20 €")
        self.assertEqual(value.grader, "PCA")
        self.assertEqual(value.qualifier, "OC / Off Center")
        self.assertIsNone(value.grade)

    def test_case_f_each_transaction_keeps_its_own_grader(self):
        lot = watcher.Lot(
            url="https://gcc.invalid/item/fixture",
            title="Fixture",
            current_price=1,
            source_type="fixed",
            body=(
                "Historique des ventes\n"
                "PSA 9\n1 août 2026\n100 €\n"
                "PCA 9.5\n2 juillet 2026\n50 €\n"
                "CA 10\n3 juin 2026\n20 €"
            ),
        )
        sales = watcher.extract_historical_sales(lot)
        self.assertEqual(
            [(sale.grader, sale.grade) for sale in sales],
            [("PSA", 9.0), ("PCA", 9.5), ("CA", 10.0)],
        )

    def test_price_first_layout_uses_one_consistent_orientation(self):
        lot = watcher.Lot(
            url="https://gcc.invalid/item/price-first",
            title="Fixture",
            current_price=1,
            source_type="fixed",
            body=(
                "Historique des ventes\n"
                "100 €\nPSA 9\nDate: 01/08/2026\n"
                "50 €\nPCA 9.5\nDate: 02/08/2026"
            ),
        )
        sales = watcher.extract_historical_sales(lot)
        self.assertEqual(
            [(sale.grader, sale.grade) for sale in sales],
            [("PSA", 9.0), ("PCA", 9.5)],
        )

    def test_case_g_note_toutes_never_becomes_grade(self):
        value = parse_historical_grade("Grader: PSA\nNote : Toutes\n100 €")
        self.assertEqual(value.grader, "PSA")
        self.assertIsNone(value.grade)

    def test_case_h_false_over_ten_is_classified_but_explicit_grade_wins(self):
        value = parse_historical_grade(
            "PCA 100 €\nGrader: PCA\nNote : 9.5\n"
            "Date: 20/05/2026\nGraphique: 50%\nNombre de ventes: 20"
        )
        self.assertEqual((value.grader, value.grade), ("PCA", "9.5"))
        self.assertGreaterEqual(value.invalid_over_ten_tokens, 1)
        self.assertTrue(
            {NON_GRADE_PRICE, NON_GRADE_DATE, NON_GRADE_CHART, NON_GRADE_COUNTER}
            .issubset(set(value.rejected_numeric_kinds))
        )

    def test_real_comparable_survives_false_price_token(self):
        lot = watcher.Lot(
            url="https://gcc.invalid/item/real-comparable",
            title="Fixture",
            current_price=1,
            source_type="fixed",
            body=(
                "Historique des ventes\n"
                "PCA 100 €\nGrader: PCA\nNote: 9.5\nDate: 20/05/2026"
            ),
        )
        counters = HistoricalParsingDiagnostics()
        sales = watcher.extract_historical_sales(lot, counters)
        self.assertEqual(len(sales), 1)
        self.assertEqual((sales[0].grader, sales[0].grade), ("PCA", 9.5))
        self.assertEqual(counters.invalid_over_ten_tokens, 1)
        self.assertEqual(counters.usable_comparables, 1)

    def test_unknown_grade_transaction_is_preserved_but_not_usable(self):
        lot = watcher.Lot(
            url="https://gcc.invalid/item/unknown",
            title="Fixture",
            current_price=1,
            source_type="fixed",
            body="Historique des ventes\nPCA 100 €\n20/05/2026",
        )
        counters = HistoricalParsingDiagnostics()
        sales = watcher.extract_historical_sales(lot, counters)
        self.assertEqual(len(sales), 1)
        self.assertIsNone(sales[0].grade)
        self.assertEqual(counters.transactions_received, 1)
        self.assertEqual(counters.grade_absent, 1)
        self.assertEqual(counters.usable_comparables, 0)

    def test_explicit_raw_transaction_is_usable_without_numeric_grade(self):
        lot = watcher.Lot(
            url="https://gcc.invalid/item/raw",
            title="Fixture",
            current_price=1,
            source_type="fixed",
            body="Historique des ventes\nNon graded\n20 €\n01/08/2026",
        )
        counters = HistoricalParsingDiagnostics()
        sales = watcher.extract_historical_sales(lot, counters)
        self.assertEqual((sales[0].grader, sales[0].grade), ("RAW", None))
        self.assertEqual(counters.usable_comparables, 1)


if __name__ == "__main__":
    unittest.main()
