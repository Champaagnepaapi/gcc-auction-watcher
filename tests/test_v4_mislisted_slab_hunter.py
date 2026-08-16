from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import run_watcher_multimarket
import watcher
import v4_focus_cert_router as focus_router
import v4_mislisted_cert_router as cert_router
import v4_mislisted_ocr_hardening as ocr_hardening
import v4_mislisted_slab_hunter as hunter


class MislistedSlabHunterTests(unittest.TestCase):
    def test_production_policy_keeps_lane_disabled_even_when_legacy_env_true(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("V4_MISLISTED_SLAB_HUNTER_ENABLED", None)
            self.assertFalse(run_watcher_multimarket._mislisted_slab_hunter_enabled())
        with patch.dict(os.environ, {"V4_MISLISTED_SLAB_HUNTER_ENABLED": "true"}):
            self.assertFalse(run_watcher_multimarket._mislisted_slab_hunter_enabled())

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

    def test_generic_official_parser_covers_common_graders(self) -> None:
        samples = (
            ("PCA", "123456789", "PCA 10 Neuf Sup'", 10.0),
            ("CGC", "1234567999", "Grade\nGem Mint 10", 10.0),
            ("BGS", "0006608830", "Final Grade\n9.5", 9.5),
            ("SGC", "1234567890", "Grade\nMINT 9", 9.0),
            ("SGS", "305000770", "Certification N°305000770\n9.5\nMINT", 9.5),
            ("CA", "123456789", "Note: 10", 10.0),
            ("ACE", "217458", "#217458\nM Rayquaza EX\nGrade\nMINT\n9", 9.0),
            ("AP", "245539", "Overall Grade: 8.5", 8.5),
            ("GEM", "12345678", "Grade 10", 10.0),
        )
        for grader, cert_number, text, expected_grade in samples:
            with self.subTest(grader=grader):
                cert = cert_router.parse_official_grade_text(text, cert_number, grader)
                self.assertEqual(cert.grade, expected_grade)
                self.assertEqual(cert.status, "OK")
                self.assertEqual(cert.grader, grader)

    def test_generic_official_parser_does_not_promote_subgrades_or_population(self) -> None:
        cert = cert_router.parse_official_grade_text(
            "Certification 123456789\nSurface 9.5\nCorners 9\nPopulation Grade 10",
            "123456789",
            "PCA",
        )
        self.assertIsNone(cert.grade)
        self.assertEqual(cert.status, hunter.CERT_GRADE_UNREADABLE)

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

    def test_focused_ocr_parser_excludes_subgrades(self) -> None:
        grade, status = ocr_hardening.parse_grade_from_ocr_text(
            "CCC GRADING\n9\nNEUF",
            "CCC",
        )
        self.assertEqual((grade, status), (9.0, "OK"))

        grade, status = ocr_hardening.parse_grade_from_ocr_text(
            "CCC 9.5\nSURFACE 8.5\nCORNERS 9",
            "CCC",
        )
        self.assertEqual((grade, status), (9.5, "OK"))

        grade, status = ocr_hardening.parse_grade_from_ocr_text(
            "SURFACE 9.5\nCORNERS 9\nEDGES 8.5",
            "CCC",
        )
        self.assertIsNone(grade)
        self.assertEqual(status, hunter.IMAGE_GRADE_UNAVAILABLE)

    def test_focused_ocr_requires_two_pass_consensus(self) -> None:
        self.assertEqual(
            ocr_hardening._grade_consensus([(10.0, "OK"), (10.0, "OK"), (None, hunter.IMAGE_GRADE_UNAVAILABLE)]),
            (10.0, "OK"),
        )
        self.assertEqual(
            ocr_hardening._grade_consensus([(10.0, "OK"), (9.0, "OK"), (None, hunter.IMAGE_GRADE_UNAVAILABLE)]),
            (None, hunter.IMAGE_GRADE_AMBIGUOUS),
        )
        self.assertEqual(
            ocr_hardening._grade_consensus([(9.5, "OK"), (None, hunter.IMAGE_GRADE_UNAVAILABLE), (None, hunter.IMAGE_GRADE_UNAVAILABLE)]),
            (None, hunter.IMAGE_GRADE_UNAVAILABLE),
        )

    def test_focused_ocr_roi_is_top_right_for_psa_pca_ccc(self) -> None:
        box = {"x": 100.0, "y": 200.0, "width": 400.0, "height": 800.0}
        for grader in ("PSA", "PCA", "CCC"):
            with self.subTest(grader=grader):
                clip = ocr_hardening._ocr_label_clip(box, grader)
                self.assertIsNotNone(clip)
                self.assertGreaterEqual(clip["x"], box["x"] + box["width"] * 0.35)
                self.assertEqual(clip["y"], box["y"])
                self.assertLessEqual(clip["height"], box["height"] * 0.30)
                self.assertLessEqual(clip["x"] + clip["width"], box["x"] + box["width"] + 0.001)

    def test_non_focus_grader_does_not_use_generic_ocr(self) -> None:
        grade, status = ocr_hardening.resolve_image_grade_from_page(object(), "BGS")
        self.assertIsNone(grade)
        self.assertEqual(status, hunter.IMAGE_GRADE_UNAVAILABLE)

    def test_api_serial_number_is_preserved_for_cert_lookup(self) -> None:
        result = {"item": {"serialNumber": "13 121 6316"}}
        self.assertEqual(hunter._serial_from_result(result), "131216316")

    def test_sgc_provider_format_reinserts_expected_hyphen(self) -> None:
        self.assertEqual(cert_router._provider_cert("SGC", "1234567890"), "1234567-890")
        self.assertEqual(cert_router._provider_cert("SGC", "1234567"), "1234567")

    def test_focus_router_prioritizes_psa_pca_ccc_and_delegates_others(self) -> None:
        page = object()
        for grader, resolver_name in (
            ("PSA", "resolve_psa_certificate"),
            ("PCA", "resolve_pca_certificate"),
            ("CCC", "resolve_ccc_certificate"),
        ):
            with self.subTest(grader=grader):
                cert = hunter.GraderCertificate("123456789", 9.0, status="OK", grader=grader)
                with patch.object(focus_router, resolver_name, return_value=cert) as resolver:
                    result = focus_router.resolve_focus_grader_certificate(page, grader, "123456789")
                resolver.assert_called_once_with(page, "123456789")
                self.assertEqual(result.grade, 9.0)

        delegated = hunter.GraderCertificate("123456789", 9.5, status="OK", grader="CGC")
        with patch.object(cert_router, "resolve_grader_certificate", return_value=delegated) as resolver:
            result = focus_router.resolve_focus_grader_certificate(page, "CGC", "123456789")
        resolver.assert_called_once_with(page, "CGC", "123456789")
        self.assertEqual(result.grade, 9.5)

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
            ocr_hardening, "resolve_image_grade_from_page", return_value=image
        ) as image_resolver, patch.object(
            hunter, "_send_mismatch_review", return_value=True
        ) as alert, patch.object(
            hunter, "_estimate_for_grade", return_value=None
        ):
            result = ocr_hardening.evaluate_with_mislisted_slab_guard(
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
        original.assert_called_once()

    def test_cert_unavailable_negative_image_mismatch_is_manual_only(self) -> None:
        lot = self._lot("10")
        cert = hunter.GraderCertificate("131216316", None, status=hunter.CERT_UNAVAILABLE, grader="PSA")
        result, original, image_resolver, alert = self._evaluate(lot, cert, image=(9.0, "OK"))
        self.assertEqual(result, "NORMAL_V4_RESULT")
        original.assert_called_once()
        image_resolver.assert_called_once()
        alert.assert_called_once()
        mismatch = alert.call_args.args[1]
        self.assertEqual(mismatch.status, hunter.NEGATIVE_GRADE_MISMATCH)
        self.assertEqual(mismatch.evidence_source, "IMAGE_OCR")

    def test_ccc_official_cert_takes_priority_over_image(self) -> None:
        lot = self._lot("9.5", grader="CCC")
        cert = hunter.GraderCertificate("544340143", 9.0, status="OK", grader="CCC")
        result, original, image_resolver, alert = self._evaluate(lot, cert, image=(10.0, "OK"))
        self.assertIsNone(result)
        image_resolver.assert_not_called()
        mismatch = alert.call_args.args[1]
        self.assertEqual(mismatch.resolved_grade, 9.0)
        self.assertEqual(mismatch.evidence_source, "OFFICIAL_CERT")

    def test_router_uses_ccc_official_adapter_before_ocr(self) -> None:
        page = object()
        ccc = hunter.GraderCertificate("544340143", 9.0, status="OK", grader="CCC")
        with patch.object(cert_router, "resolve_ccc_certificate", return_value=ccc) as resolver:
            result = cert_router.resolve_grader_certificate(page, "ccc", "544340143")
        resolver.assert_called_once_with(page, "544340143")
        self.assertEqual(result.grade, 9.0)

    def test_router_routes_supported_graders_to_official_adapter(self) -> None:
        page = object()
        cases = (
            ("PCA", "resolve_pca_certificate", (page, "123456789")),
            ("CGC", "resolve_cgc_certificate", (page, "123456789")),
            ("BGS", "resolve_beckett_certificate", ("BGS", "123456789")),
            ("SGC", "resolve_sgc_certificate", (page, "123456789")),
            ("SGS", "resolve_sgs_certificate", ("123456789",)),
            ("CA", "resolve_collectaura_certificate", (page, "123456789")),
            ("ACE", "resolve_ace_certificate", ("123456789",)),
            ("GRAAD", "resolve_graad_certificate", ("123456789",)),
            ("AP", "resolve_ap_certificate", (page, "123456789")),
            ("GEM", "resolve_gem_certificate", (page, "123456789")),
        )
        for grader, resolver_name, expected_args in cases:
            with self.subTest(grader=grader):
                cert = hunter.GraderCertificate("123456789", 9.0, status="OK", grader=grader)
                with patch.object(cert_router, resolver_name, return_value=cert) as resolver:
                    result = cert_router.resolve_grader_certificate(page, grader, "123456789")
                resolver.assert_called_once_with(*expected_args)
                self.assertEqual(result.grade, 9.0)

    def test_collectaura_alias_routes_to_ca_official_adapter(self) -> None:
        page = object()
        cert = hunter.GraderCertificate("123456789", 10.0, status="OK", grader="CA")
        with patch.object(cert_router, "resolve_collectaura_certificate", return_value=cert) as resolver:
            result = cert_router.resolve_grader_certificate(page, "CollectAura", "123456789")
        resolver.assert_called_once_with(page, "123456789")
        self.assertEqual(result.grader, "CA")

    def test_unknown_grader_returns_cert_unavailable(self) -> None:
        cert = cert_router.resolve_grader_certificate(object(), "UNKNOWN", "123456789")
        self.assertIsNone(cert.grade)
        self.assertEqual(cert.status, hunter.CERT_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
