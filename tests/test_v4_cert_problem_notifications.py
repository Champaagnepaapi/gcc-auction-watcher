from __future__ import annotations

import os
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from email.header import Header
from unittest.mock import Mock, patch

import run_watcher_multimarket
import watcher
import v4_cert_problem_notifications as cert_alerts
import v4_mislisted_slab_hunter as hunter


class CertProblemNotificationTests(unittest.TestCase):
    def test_immediate_cert_problem_notifications_are_safe_off_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("V4_CERT_PROBLEM_NOTIFICATIONS_ENABLED", None)
            self.assertFalse(run_watcher_multimarket._cert_problem_notifications_enabled())
        with patch.dict(os.environ, {"V4_CERT_PROBLEM_NOTIFICATIONS_ENABLED": "true"}):
            self.assertTrue(run_watcher_multimarket._cert_problem_notifications_enabled())

    def _lot(
        self,
        *,
        grader: str = "PSA",
        grade: str = "9",
        cert_number: str = "131216316",
    ) -> watcher.Lot:
        dimensions = {"cert_number": cert_number} if cert_number else {}
        return watcher.Lot(
            url=f"https://gradedcardcenter.com/item/cert-alert-{grader.lower()}",
            title=f"{grader} {grade} Bulbasaur",
            current_price=55.0,
            source_type="fixed",
            body="Catégorie: Pokémon\nRéférence: #166/165\n",
            grader=grader,
            grade=grade,
            card_number="166/165",
            language="Japanese",
            commercial_dimensions=dimensions,
        )

    def _evaluate(self, lot, *, resolved=None, attempted=True, state=None, delegate_result="NORMAL"):
        if resolved is None:
            resolved = hunter.GraderCertificate(
                "131216316", None, status=hunter.CERT_UNAVAILABLE, grader=lot.grader
            )
        delegate = Mock(return_value=delegate_result)
        alert = Mock(return_value=True)
        with patch.object(cert_alerts, "_DELEGATE_EVALUATE", delegate), patch.object(
            cert_alerts,
            "_resolve_cert_with_attempt_marker",
            return_value=(resolved, attempted),
        ), patch.object(cert_alerts, "_send_cert_problem_review", alert):
            result = cert_alerts.evaluate_with_cert_problem_notifications(
                object(),
                lot,
                1,
                state if state is not None else {},
                "2026-08-15T10:00:00Z",
                datetime(2026, 8, 15, tzinfo=timezone.utc),
                watcher.RunDiagnostics(),
            )
        return result, delegate, alert

    def test_fixed_api_cert_number_is_preserved_before_detail_page(self) -> None:
        base_lot = self._lot(cert_number="")
        result = {"item": {"serialNumber": "13 121 6316"}}
        with patch.object(cert_alerts, "_ORIGINAL_FIXED_API_LOT", return_value=base_lot):
            lot = cert_alerts._fixed_api_lot_with_serial(result, base_lot.url, object())
        self.assertEqual(lot.commercial_dimensions["cert_number"], "131216316")

    def test_inspection_cannot_erase_structured_api_cert_number(self) -> None:
        original = replace(self._lot(), body="")
        inspected_without_cert = replace(
            original,
            body="Catégorie: Pokémon\nRéférence: #166/165\n",
            commercial_dimensions={},
        )
        cert = hunter.GraderCertificate("131216316", 9.0, status="OK", grader="PSA")
        delegate = Mock(return_value="NORMAL")
        alert = Mock(return_value=True)
        with patch.object(watcher, "inspect_item", return_value=inspected_without_cert), patch.object(
            cert_alerts, "_DELEGATE_EVALUATE", delegate
        ), patch.object(
            cert_alerts,
            "_resolve_cert_with_attempt_marker",
            return_value=(cert, True),
        ) as resolver, patch.object(
            cert_alerts, "_send_cert_problem_review", alert
        ), patch.object(
            cert_alerts, "_serial_from_gradation_panel"
        ) as panel:
            result = cert_alerts.evaluate_with_cert_problem_notifications(
                object(), original, 1, {}, "now",
                datetime(2026, 8, 15, tzinfo=timezone.utc), watcher.RunDiagnostics()
            )
        self.assertEqual(result, "NORMAL")
        resolver.assert_called_once_with(unittest.mock.ANY, "PSA", "131216316")
        panel.assert_not_called()
        alert.assert_not_called()
        delegated_lot = delegate.call_args.args[1]
        self.assertEqual(delegated_lot.commercial_dimensions["cert_number"], "131216316")

    def test_gradation_panel_is_checked_before_missing_cert_alert(self) -> None:
        lot = self._lot(cert_number="")
        cert = hunter.GraderCertificate("131216316", 9.0, status="OK", grader="PSA")
        delegate = Mock(return_value="NORMAL")
        alert = Mock(return_value=True)
        with patch.object(cert_alerts, "_DELEGATE_EVALUATE", delegate), patch.object(
            cert_alerts, "_serial_from_gradation_panel", return_value="131216316"
        ) as panel, patch.object(
            cert_alerts,
            "_resolve_cert_with_attempt_marker",
            return_value=(cert, True),
        ) as resolver, patch.object(
            cert_alerts, "_send_cert_problem_review", alert
        ):
            result = cert_alerts.evaluate_with_cert_problem_notifications(
                object(), lot, 1, {}, "now",
                datetime(2026, 8, 15, tzinfo=timezone.utc), watcher.RunDiagnostics()
            )
        self.assertEqual(result, "NORMAL")
        panel.assert_called_once_with(unittest.mock.ANY, lot.url)
        resolver.assert_called_once_with(unittest.mock.ANY, "PSA", "131216316")
        alert.assert_not_called()
        delegated_lot = delegate.call_args.args[1]
        self.assertEqual(delegated_lot.commercial_dimensions["cert_number"], "131216316")

    def test_gradation_text_parser_reads_split_cert_label(self) -> None:
        self.assertEqual(
            cert_alerts._serial_from_text("Description\nGradation\nCertification\n13 121 6316\nGrade\n9"),
            "131216316",
        )

    def test_missing_cert_number_alerts_only_after_gradation_fallback_fails(self) -> None:
        lot = self._lot(cert_number="")
        delegate = Mock(return_value="NORMAL")
        alert = Mock(return_value=True)
        with patch.object(cert_alerts, "_DELEGATE_EVALUATE", delegate), patch.object(
            cert_alerts, "_send_cert_problem_review", alert
        ), patch.object(
            cert_alerts, "_serial_from_gradation_panel", return_value=""
        ) as panel, patch.object(cert_alerts, "_resolve_cert_with_attempt_marker") as resolver:
            result = cert_alerts.evaluate_with_cert_problem_notifications(
                object(), lot, 1, {}, "now",
                datetime(2026, 8, 15, tzinfo=timezone.utc), watcher.RunDiagnostics()
            )
        self.assertEqual(result, "NORMAL")
        panel.assert_called_once()
        resolver.assert_not_called()
        alert.assert_called_once()
        self.assertEqual(alert.call_args.kwargs["issue"], cert_alerts.CERT_NUMBER_MISSING)
        delegate.assert_called_once()

    def test_attempted_lookup_failure_alerts_even_when_v4_finds_no_opportunity(self) -> None:
        lot = self._lot()
        cert = hunter.GraderCertificate(
            "131216316", None, status=hunter.CERT_UNAVAILABLE, grader="PSA"
        )
        result, delegate, alert = self._evaluate(
            lot, resolved=cert, attempted=True, delegate_result=None
        )
        self.assertIsNone(result)
        alert.assert_called_once()
        self.assertEqual(alert.call_args.kwargs["issue"], cert_alerts.CERT_LOOKUP_FAILED)
        delegate.assert_called_once()

    def test_unreadable_official_grade_alerts_immediately(self) -> None:
        lot = self._lot(grader="CCC", cert_number="544340143")
        cert = hunter.GraderCertificate(
            "544340143", None, status=hunter.CERT_GRADE_UNREADABLE, grader="CCC"
        )
        _, _, alert = self._evaluate(lot, resolved=cert, attempted=True)
        alert.assert_called_once()
        self.assertEqual(alert.call_args.kwargs["issue"], cert_alerts.CERT_GRADE_UNREADABLE)

    def test_budget_exhaustion_without_real_lookup_is_not_mislabeled_as_cert_problem(self) -> None:
        lot = self._lot(grader="PCA")
        cert = hunter.GraderCertificate(
            "131216316", None, status=hunter.CERT_UNAVAILABLE, grader="PCA"
        )
        result, delegate, alert = self._evaluate(lot, resolved=cert, attempted=False)
        self.assertEqual(result, "NORMAL")
        alert.assert_not_called()
        delegate.assert_called_once()

    def test_successful_official_cert_does_not_emit_cert_problem_alert(self) -> None:
        lot = self._lot()
        cert = hunter.GraderCertificate("131216316", 9.0, status="OK", grader="PSA")
        result, delegate, alert = self._evaluate(lot, resolved=cert, attempted=True)
        self.assertEqual(result, "NORMAL")
        alert.assert_not_called()
        delegate.assert_called_once()

    def test_cert_problem_ntfy_is_deduplicated_by_listing_and_problem(self) -> None:
        lot = self._lot()
        state = {}
        response = Mock()
        response.raise_for_status.return_value = None
        with patch.object(watcher, "NTFY_TOPIC", "test-topic"), patch.object(
            watcher.requests, "post", return_value=response
        ) as post:
            first = cert_alerts._send_cert_problem_review(
                lot,
                state,
                grader="PSA",
                cert_number="131216316",
                issue=cert_alerts.CERT_LOOKUP_FAILED,
                cert_status=hunter.CERT_UNAVAILABLE,
            )
            second = cert_alerts._send_cert_problem_review(
                lot,
                state,
                grader="PSA",
                cert_number="131216316",
                issue=cert_alerts.CERT_LOOKUP_FAILED,
                cert_status=hunter.CERT_UNAVAILABLE,
            )
        self.assertTrue(first)
        self.assertFalse(second)
        post.assert_called_once()
        self.assertEqual(
            post.call_args.kwargs["headers"]["Title"],
            Header("CERT LOOKUP FAILED — MANUAL REVIEW", "utf-8").encode(),
        )
        payload = post.call_args.kwargs["data"].decode("utf-8")
        self.assertIn("CERT_LOOKUP_FAILED", payload)
        self.assertIn("ne prouve pas un mislisting", payload)


if __name__ == "__main__":
    unittest.main()
