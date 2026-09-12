from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import watcher
import v4_global_marketplace_pricecharting_diagnostics as diagnostics
import v4_pricecharting_valuation as pc


class PriceChartingDiagnosticsTests(unittest.TestCase):
    def lot(self):
        return watcher.Lot(
            url="https://example.test/card",
            title="Pikachu",
            current_price=50.0,
            source_type="FIXED_PRICE",
            grader="PSA",
            grade="10",
            card_set="Pokemon 151",
            card_number="025/165",
            language="Japanese",
        )

    def test_wrapper_returns_original_lookup_unchanged(self):
        expected = pc.PriceChartingLookup(
            "CLEAN_NO_MATCH",
            product_id="https://www.pricecharting.com/game/test",
            note="coordinate conflict",
        )
        original = diagnostics._ORIGINAL_LOOKUP
        try:
            diagnostics._ORIGINAL_LOOKUP = lambda _self, _lot: expected
            diagnostics._count = 0
            with patch.object(diagnostics, "_enabled", return_value=True):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = diagnostics._lookup_with_diagnostics(object(), self.lot())
            self.assertIs(result, expected)
            text = buffer.getvalue()
            self.assertIn("[PRICECHARTING_DIAG]", text)
            self.assertIn("status=CLEAN_NO_MATCH", text)
            self.assertIn("number=025/165", text)
        finally:
            diagnostics._ORIGINAL_LOOKUP = original
            diagnostics._count = 0

    def test_disabled_diagnostics_emit_nothing(self):
        expected = pc.PriceChartingLookup("MATCHED", value_usd=100.0)
        original = diagnostics._ORIGINAL_LOOKUP
        try:
            diagnostics._ORIGINAL_LOOKUP = lambda _self, _lot: expected
            with patch.object(diagnostics, "_enabled", return_value=False):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    result = diagnostics._lookup_with_diagnostics(object(), self.lot())
            self.assertIs(result, expected)
            self.assertEqual(buffer.getvalue(), "")
        finally:
            diagnostics._ORIGINAL_LOOKUP = original


if __name__ == "__main__":
    unittest.main()
