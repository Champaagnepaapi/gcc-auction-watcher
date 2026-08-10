from __future__ import annotations

import unittest
from types import SimpleNamespace

import watcher
from run_watcher_safe import (
    external_exact_target_grade_count,
    grade_arbitrage_external_validation_sufficient,
)


class GradeArbitrageGuardTests(unittest.TestCase):
    @staticmethod
    def _op(*, ebay=(), apr=(), grade_arbitrage=True):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/test",
            title="PSA 8 Abo",
            current_price=50.0,
            source_type="fixed",
            grader="PSA",
            grade="8",
        )
        return SimpleNamespace(
            lot=lot,
            estimate=SimpleNamespace(grade_arbitrage=grade_arbitrage),
            ebay_comparables=list(ebay),
            psa_apr_comparables=list(apr),
        )

    @staticmethod
    def _sale(*, grader="PSA", grade=8.0, exact=True):
        return watcher.ComparableSale(
            price=20.0,
            source="ebay",
            grader=grader,
            grade=grade,
            exact_card=exact,
        )

    def test_abo_style_zero_external_exact_grade_comps_is_rejected(self):
        op = self._op()
        self.assertEqual(external_exact_target_grade_count(op), 0)
        self.assertFalse(grade_arbitrage_external_validation_sufficient(op))

    def test_wrong_grade_or_wrong_grader_does_not_confirm_arbitrage(self):
        op = self._op(
            ebay=(self._sale(grade=6.0), self._sale(grader="PCA", grade=8.0))
        )
        self.assertEqual(external_exact_target_grade_count(op), 0)
        self.assertFalse(grade_arbitrage_external_validation_sufficient(op))

    def test_two_exact_target_grade_external_comps_confirm_arbitrage(self):
        op = self._op(
            ebay=(self._sale(),),
            apr=(self._sale(),),
        )
        self.assertEqual(external_exact_target_grade_count(op), 2)
        self.assertTrue(grade_arbitrage_external_validation_sufficient(op))

    def test_regular_discount_opportunity_is_not_blocked(self):
        op = self._op(grade_arbitrage=False)
        self.assertTrue(grade_arbitrage_external_validation_sufficient(op))


if __name__ == "__main__":
    unittest.main()
