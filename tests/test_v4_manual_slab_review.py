from __future__ import annotations

import unittest
from datetime import datetime, timezone
from email.header import Header
from unittest.mock import Mock, patch

import watcher
import v4_manual_slab_review as manual_review
import v4_mislisted_ocr_hardening as ocr
import v4_mislisted_slab_hunter as hunter


# PR66 canonical handoff is recorded in README.md; this comment intentionally
# retriggers CI after the docs-only bot commit so the exact final PR head is validated.
class ManualSlabReviewTests(unittest.TestCase):
    def _lot(self, grader: str = "PCA", grade: str = "9.5") -> watcher.Lot:
        return watcher.Lot(
            url=f"https://gradedcardcenter.com/item/manual-review-{grader.lower()}",
            title=f"{grader} {grade} Pikachu",
            current_price=50.0,
            source_type="fixed",
            body="Catégorie: Pokémon\nRéférence: #25/102\n",
            grader=grader,
            grade=grade,
            card_number="25/102",
            language="French",
            commercial_dimensions={"cert_number": "123456789"},
        )

    def _opportunity(self, *, flagged: bool = True) -> watcher.Opportunity:
        lot = self._lot()
        if flagged:
            lot.commercial_dimensions.update(
                {
                    ocr.MANUAL_SLAB_REVIEW_FLAG: ocr.MANUAL_SLAB_REVIEW_UNRESOLVED,
                    ocr.MANUAL_SLAB_CERT_STATUS: hunter.CERT_UNAVAILABLE,
                    ocr.MANUAL_SLAB_OCR_STATUS: hunter.IMAGE_GRADE_AMBIGUOUS,
                    ocr.MANUAL_SLAB_CERT_NUMBER: "123456789",
                }
            )
        estimate = watcher.MarketEstimate(
            low=80.0,
            central=100.0,
            high=115.0,
            kept_comparables=[],
            rejected_outliers=[],
            recent_90_count=3,
            dated_count=3,
            liquidity="moyenne",
            dispersion="faible",
            confidence="moyenne",
            adaptive_discount_pct=30.0,
            rationale="test",
            source_counts={"gcc": 3},
            exact_grade_count=3,
            same_grader_count=3,
        )
        return watcher.Opportunity(
            lot=lot,
            estimate=estimate,
            discount_pct=50.0,
            max_recommended=70.0,
            gcc_comparables=[],
            ebay_comparables=[],
            valuation_path=watcher.PATH_GCC_ONLY,
            evidence_summary="GCC test",
        )

    def _evaluate_unresolved(self, grader: str, image_status: str):
        lot = self._lot(grader=grader, grade="9" if grader == "PSA" else "9.5")
        cert = hunter.GraderCertificate(
            "123456789", None, status=hunter.CERT_UNAVAILABLE, grader=grader
        )
        original = Mock(return_value="NORMAL_V4_RESULT")
        with patch.object(hunter, "resolve_grader_certificate", return_value=cert), patch.object(
            ocr, "resolve_image_grade_from_page", return_value=(None, image_status)
        ), patch.object(hunter, "_ORIGINAL_EVALUATE", original):
            result = ocr.evaluate_with_mislisted_slab_guard(
                object(),
                lot,
                1,
                {},
                "2026-08-15T09:00:00Z",
                datetime(2026, 8, 15, tzinfo=timezone.utc),
                watcher.RunDiagnostics(),
            )
        return lot, result, original

    def test_focus_graders_mark_cert_plus_ambiguous_ocr_for_later_review(self) -> None:
        for grader in ("PSA", "PCA", "CCC"):
            with self.subTest(grader=grader):
                lot, result, original = self._evaluate_unresolved(
                    grader, hunter.IMAGE_GRADE_AMBIGUOUS
                )
                self.assertEqual(result, "NORMAL_V4_RESULT")
                original.assert_called_once()
                self.assertEqual(
                    lot.commercial_dimensions[ocr.MANUAL_SLAB_REVIEW_FLAG],
                    ocr.MANUAL_SLAB_REVIEW_UNRESOLVED,
                )
                self.assertEqual(
                    lot.commercial_dimensions[ocr.MANUAL_SLAB_OCR_STATUS],
                    hunter.IMAGE_GRADE_AMBIGUOUS,
                )

    def test_focus_grader_marks_cert_plus_unavailable_ocr_for_later_review(self) -> None:
        lot, result, _ = self._evaluate_unresolved(
            "PCA", hunter.IMAGE_GRADE_UNAVAILABLE
        )
        self.assertEqual(result, "NORMAL_V4_RESULT")
        self.assertEqual(
            lot.commercial_dimensions[ocr.MANUAL_SLAB_REVIEW_FLAG],
            ocr.MANUAL_SLAB_REVIEW_UNRESOLVED,
        )
        self.assertEqual(
            lot.commercial_dimensions[ocr.MANUAL_SLAB_OCR_STATUS],
            hunter.IMAGE_GRADE_UNAVAILABLE,
        )

    def test_official_cert_success_does_not_create_unresolved_marker(self) -> None:
        lot = self._lot(grader="CCC", grade="9")
        cert = hunter.GraderCertificate("123456789", 9.0, status="OK", grader="CCC")
        with patch.object(hunter, "resolve_grader_certificate", return_value=cert), patch.object(
            ocr, "resolve_image_grade_from_page"
        ) as image_resolver, patch.object(
            hunter, "_ORIGINAL_EVALUATE", Mock(return_value="NORMAL_V4_RESULT")
        ):
            result = ocr.evaluate_with_mislisted_slab_guard(
                object(), lot, 1, {}, "now",
                datetime(2026, 8, 15, tzinfo=timezone.utc), watcher.RunDiagnostics()
            )
        self.assertEqual(result, "NORMAL_V4_RESULT")
        image_resolver.assert_not_called()
        self.assertNotIn(ocr.MANUAL_SLAB_REVIEW_FLAG, lot.commercial_dimensions)

    def test_non_focus_grader_does_not_create_unresolved_marker(self) -> None:
        lot, result, _ = self._evaluate_unresolved(
            "CGC", hunter.IMAGE_GRADE_UNAVAILABLE
        )
        self.assertEqual(result, "NORMAL_V4_RESULT")
        self.assertNotIn(ocr.MANUAL_SLAB_REVIEW_FLAG, lot.commercial_dimensions)

    def test_final_opportunity_forces_one_manual_review_notification(self) -> None:
        op = self._opportunity(flagged=True)
        base = watcher.NotificationDecision(False, False, ())
        delegate = Mock(return_value=base)
        with patch.object(manual_review, "_DELEGATE_NOTIFICATION_DECISION", delegate):
            first = manual_review.notification_decision_with_manual_slab_review(op, {})
            second = manual_review.notification_decision_with_manual_slab_review(
                op, {manual_review.MANUAL_REVIEW_STATE_SENT: True}
            )
        self.assertTrue(first.should_notify)
        self.assertIn(manual_review.MANUAL_REVIEW_REASON, first.reasons)
        self.assertFalse(second.should_notify)

    def test_state_records_manual_review_sent_and_statuses(self) -> None:
        op = self._opportunity(flagged=True)
        decision = watcher.NotificationDecision(
            True, False, (manual_review.MANUAL_REVIEW_REASON,)
        )
        delegate = Mock(return_value={"price": 50.0})
        with patch.object(manual_review, "_DELEGATE_UPDATED_NOTIFICATION_STATE", delegate):
            state = manual_review.updated_notification_state_with_manual_slab_review(
                op, {}, decision, "2026-08-15T09:00:00Z"
            )
        self.assertTrue(state[manual_review.MANUAL_REVIEW_STATE_SENT])
        self.assertEqual(state[ocr.MANUAL_SLAB_CERT_STATUS], hunter.CERT_UNAVAILABLE)
        self.assertEqual(state[ocr.MANUAL_SLAB_OCR_STATUS], hunter.IMAGE_GRADE_AMBIGUOUS)

    def test_manual_review_sends_one_dedicated_ntfy_payload(self) -> None:
        op = self._opportunity(flagged=True)
        decision = watcher.NotificationDecision(
            True, False, ("nouvelle opportunité", manual_review.MANUAL_REVIEW_REASON)
        )
        response = Mock()
        response.raise_for_status.return_value = None
        delegate = Mock()
        with patch.object(manual_review, "_DELEGATE_NOTIFY", delegate), patch.object(
            watcher, "NTFY_TOPIC", "test-topic"
        ), patch.object(watcher.requests, "post", return_value=response) as post:
            manual_review.notify_with_manual_slab_review(op, decision)
        delegate.assert_not_called()
        post.assert_called_once()
        kwargs = post.call_args.kwargs
        self.assertEqual(
            kwargs["headers"]["Title"],
            Header(manual_review.MANUAL_REVIEW_TITLE, "utf-8").encode(),
        )
        payload = kwargs["data"].decode("utf-8")
        self.assertIn("GRADE NON CONFIRMÉ", payload)
        self.assertIn("CERT_UNAVAILABLE", payload)
        self.assertIn("IMAGE_GRADE_AMBIGUOUS", payload)
        self.assertIn("Prix max conseillé : 70.00 €", payload)

    def test_normal_opportunity_still_delegates_to_existing_notifier(self) -> None:
        op = self._opportunity(flagged=False)
        decision = watcher.NotificationDecision(True, False, ("nouvelle opportunité",))
        delegate = Mock()
        with patch.object(manual_review, "_DELEGATE_NOTIFY", delegate):
            manual_review.notify_with_manual_slab_review(op, decision)
        delegate.assert_called_once_with(op, decision)


if __name__ == "__main__":
    unittest.main()
