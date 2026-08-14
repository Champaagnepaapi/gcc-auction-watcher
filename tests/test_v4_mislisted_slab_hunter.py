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

    def test_parse_official_ccc_cert_grade(self) -> None:
        cert = hunter.parse_ccc_verification_text(
            "N° de certification 544340143 Carte Shaymin Note 9 Neuf GradeReport",
            "544340143",
        )
        self.assertEqual(cert.cert_number, "544340143")
        self.assertEqual(cert.grade, 9.0)
        self.assertEqual(cert.status, "OK")
        self.assertEqual(cert.grader, "CCC")

    def test_positive_and_negative_grade_direction(self) -> None:
        positive = hunter.classify_grade_mismatch(8, certificate_grade=9)
        negative = hunter.classify_grade_mismatch(10, certificate_grade=9)
        same = hunter.classify_grade_mismatch(9, certificate_grade=9)
        image_only = hunter.classify_grade_mismatch(8, image_grade=10)
        self.assertEqual(positive.status, hunter.POSITIVE_GRADE_MISMATCH)
        self.assertEqual(negative.status, hunter.NEGATIVE_GRADE_MISMATCH)
        self.assertEqual(same.status, hunter.GRADE_MATCH)
        self.assertEqual(image_only.evidence_source, "IMAGE_OCR")
        self.assertTrue(positive.manual_verification_required)

    def test_ocr_parser_requires_unambiguous_grade(self) -> None:
        grade, status = hunter.parse_grade_from_ocr_text("CCC GRADING\n9\nNEUF", "CCC")
        self.assertEqual((grade, status), (9.0, "OK"))
        grade, status = hunter.parse_grade_from_ocr_text("CCC 9.5\nSURFACE 8.5", "CCC")
        self.assertIsNone(grade)
        self.assertEqual(status, hunter.IMAGE_GRADE_AMBIGUOUS)

    def test_api_serial_number_is_preserved_for_cert_lookup(self) -> None:
        result = {"item": {"serialNumber": "13 121 6316"}}
        self.assertEqual(hunter._serial_from_result(result), "131216316")

    def _lot(self, grade: str, grader: str = "PSA") -> watcher.Lot:
        return watcher.Lot(
            url="https://gradedcardcenter.com/item/test-mismatch",
            title=f"{grader} {grade} Bulbasaur",
            current_price=55.0,
            source_type="auction",
            minutes_to_end=10,
            body="Catégorie: Pokémon\nRéférence: #166/165\n",
            grader=grader,
            grade=grade,
            card_number="166/165",
            language="Japanese",
            commercial_dimensions={"cert_number": "131216316"},
        )

    def _evaluate(self, lot, cert, image=(None, hunter.IMAGE_GRADE_UNAVAILABLE)):
        diagnostics = watcher.RunDiagnostics()
        original = Mock(return_value="NORMAL_V4_RESULT")
        with patch.object(hunter, "_ORIGINAL_EVALUATE", original), patch.object(
            hunter, "resolve_grader_certificate", return_value=cert
        ), patch.object(
            hunter, "resolve_image_grade_from_page", return_value=image
        ) as image_resolver, patch.object(
            hunter, "_send_mismatch_review", return_value=True
        ) as alert, patch.object(
            hunter, "_estimate_for_grade", return_value=None
        ):
            result = hunter.evaluate_with_mislisted_slab_guard(
                object(), lot, 1, {}, "2026-08-14T18:00:00Z",
                datetime(2026, 8, 14, tzinfo=timezone.utc), diagnostics
            )
        return result, original, image_resolver, alert

    def test_negative_official_cert_mismatch_blocks_economic_opportunity(self) -> None:
        lot = self._lot("10")
        cert = hunter.GraderCertificate("131216316", 9.0, status="OK", grader="PSA")
        result, original, image_resolver, alert = self._evaluate(lot, cert)
        self.assertIsNone(result)
        original.assert_not_called()
        image_resolver.assert_not_called()
        alert.assert_called_once()

    def test_positive_official_cert_mismatch_alerts_but_keeps_normal_v4_path(self) -> None:
        lot = self._lot("8")
        cert = hunter.GraderCertificate("131216316", 9.0, status="OK", grader="PSA")
        result, original, image_resolver, alert = self._evaluate(lot, cert)
        self.assertEqual(result, "NORMAL_V4_RESULT")
        image_resolver.assert_not_called()
        alert.assert_called_once()
        original.assert_called_once()

    def test_cert_unavailable_positive_image_mismatch_still_alerts(self) -> None:
        lot = self._lot("8")
        cert = hunter.GraderCertificate("131216316", None, status=hunter.CERT_UNAVAILABLE, grader="PSA")
        result, original, image_resolver, alert = self._evaluate(lot, cert, image=(10.0, "OK"))
        self.assertEqual(result, "NORMAL_V4_RESULT")
        image_resolver.assert_called_once()
        alert.assert_called_once()
        mismatch = alert.call_args.args[1]
        self.assertEqual(mismatch.status, hunter.POSITIVE_GRADE_MISMATCH)
        self.assertEqual(mismatch.evidence_source, "IMAGE_OCR")

    def test_cert_unavailable_negative_image_mismatch_blocks_normal_alert(self) -> None:
        lot = self._lot("10")
        cert = hunter.GraderCertificate("131216316", None, status=hunter.CERT_UNAVAILABLE, grader="PSA")
        result, original, image_resolver, alert = self._evaluate(lot, cert, image=(9.0, "OK"))
        self.assertIsNone(result)
        original.assert_not_called()
        image_resolver.assert_called_once()
        alert.assert_called_once()

    def test_ccc_official_cert_takes_priority_over_image(self) -> None:
        lot = self._lot("9.5", grader="CCC")
        cert = hunter.GraderCertificate("544340143", 9.0, status="OK", grader="CCC")
        result, original, image_resolver, alert = self._evaluate(lot, cert, image=(10.0, "OK"))
        self.assertIsNone(result)
        image_resolver.assert_not_called()
        mismatch = alert.call_args.args[1]
        self.assertEqual(mismatch.resolved_grade, 9.0)
        self.assertEqual(mismatch.evidence_source, "OFFICIAL_CERT")


if __name__ == "__main__":
    unittest.main()
