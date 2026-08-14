from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import run_watcher_multimarket
import watcher
import v4_mislisted_slab_hunter as hunter


class MislistedSlabHunterTests(unittest.TestCase):
    def test_safe_off_default_and_explicit_enable(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("V4_MISLISTED_SLAB_HUNTER_ENABLED", None)
            self.assertFalse(run_watcher_multimarket._mislisted_slab_hunter_enabled())
        with patch.dict(os.environ, {"V4_MISLISTED_SLAB_HUNTER_ENABLED": "true"}):
            self.assertTrue(run_watcher_multimarket._mislisted_slab_hunter_enabled())

    def test_parse_official_psa_cert_grade(self) -> None:
        raw = """
        <h1>PSA Certification #131216316</h1>
        <table>
          <tr><td>Certification Number</td><td>131216316</td></tr>
          <tr><td>Year</td><td>2023</td></tr>
          <tr><td>Card Number</td><td>166</td></tr>
          <tr><td>Player</td><td>BULBASAUR</td></tr>
          <tr><td>Grade</td><td>GEM MT 10</td></tr>
        </table>
        """
        cert = hunter.parse_psa_certificate_html(raw, "131216316")
        self.assertEqual(cert.cert_number, "131216316")
        self.assertEqual(cert.grade, 10.0)
        self.assertEqual(cert.card_number, "166")
        self.assertEqual(cert.subject, "BULBASAUR")
        self.assertEqual(cert.status, "OK")

    def test_positive_and_negative_grade_direction(self) -> None:
        positive = hunter.classify_grade_mismatch(8, certificate_grade=9)
        negative = hunter.classify_grade_mismatch(10, certificate_grade=9)
        same = hunter.classify_grade_mismatch(9, certificate_grade=9)
        self.assertEqual(positive.status, hunter.POSITIVE_GRADE_MISMATCH)
        self.assertEqual(negative.status, hunter.NEGATIVE_GRADE_MISMATCH)
        self.assertEqual(same.status, hunter.GRADE_MATCH)
        self.assertTrue(positive.manual_verification_required)

    def test_api_serial_number_is_preserved_for_cert_lookup(self) -> None:
        result = {"item": {"serialNumber": "13 121 6316"}}
        self.assertEqual(hunter._serial_from_result(result), "131216316")

    def _lot(self, grade: str) -> watcher.Lot:
        return watcher.Lot(
            url="https://gradedcardcenter.com/item/test-mismatch",
            title=f"PSA {grade} Bulbasaur",
            current_price=55.0,
            source_type="auction",
            minutes_to_end=10,
            body="Catégorie: Pokémon\nRéférence: #166/165\n",
            grader="PSA",
            grade=grade,
            card_number="166/165",
            language="Japanese",
            commercial_dimensions={"cert_number": "131216316"},
        )

    def test_negative_mismatch_blocks_economic_opportunity(self) -> None:
        lot = self._lot("10")
        cert = hunter.PsaCertificate("131216316", 9.0, status="OK")
        diagnostics = watcher.RunDiagnostics()
        original = Mock(return_value="SHOULD_NOT_RUN")
        with patch.object(hunter, "_ORIGINAL_EVALUATE", original), patch.object(
            hunter, "resolve_psa_certificate", return_value=cert
        ), patch.object(hunter, "_send_mismatch_review", return_value=True), patch.object(
            hunter, "_estimate_for_grade", return_value=None
        ):
            result = hunter.evaluate_with_mislisted_slab_guard(
                object(), lot, 1, {}, "2026-08-14T18:00:00Z",
                datetime(2026, 8, 14, tzinfo=timezone.utc), diagnostics
            )
        self.assertIsNone(result)
        original.assert_not_called()

    def test_positive_mismatch_alerts_but_keeps_normal_v4_path(self) -> None:
        lot = self._lot("8")
        cert = hunter.PsaCertificate("131216316", 9.0, status="OK")
        diagnostics = watcher.RunDiagnostics()
        original = Mock(return_value="NORMAL_V4_RESULT")
        with patch.object(hunter, "_ORIGINAL_EVALUATE", original), patch.object(
            hunter, "resolve_psa_certificate", return_value=cert
        ), patch.object(hunter, "_send_mismatch_review", return_value=True) as alert, patch.object(
            hunter, "_estimate_for_grade", return_value=None
        ):
            result = hunter.evaluate_with_mislisted_slab_guard(
                object(), lot, 1, {}, "2026-08-14T18:00:00Z",
                datetime(2026, 8, 14, tzinfo=timezone.utc), diagnostics
            )
        self.assertEqual(result, "NORMAL_V4_RESULT")
        alert.assert_called_once()
        original.assert_called_once()


if __name__ == "__main__":
    unittest.main()
