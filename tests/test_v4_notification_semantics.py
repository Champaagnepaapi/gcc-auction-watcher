from __future__ import annotations

import unittest
from unittest.mock import patch

import watcher
import v4_notification_semantics as semantics


class _OkResponse:
    def raise_for_status(self) -> None:
        return None


def _op(path: str) -> watcher.Opportunity:
    lot = watcher.Lot(
        url="https://gradedcardcenter.com/item/test",
        title="PCA 10 Testmon",
        current_price=40.0,
        source_type="auction",
        grader="PCA",
        grade="10",
    )
    estimate = watcher.MarketEstimate(
        low=60.0,
        central=70.0,
        high=75.0,
        kept_comparables=[],
        rejected_outliers=[],
        recent_90_count=0,
        dated_count=0,
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
        discount_pct=42.8,
        max_recommended=49.0,
        gcc_comparables=[],
        ebay_comparables=[],
        valuation_path=path,
    )


class NotificationSemanticsTests(unittest.TestCase):
    def test_titles_distinguish_confirmed_pending_and_gcc_only(self) -> None:
        decision = watcher.NotificationDecision(True)
        self.assertEqual(
            semantics.opportunity_title(_op(watcher.PATH_GCC_EXTERNAL_CONFIRMED), decision),
            "GCC AUCTION — FORTE OPPORTUNITÉ CONFIRMÉE",
        )
        self.assertEqual(
            semantics.opportunity_title(_op(watcher.PATH_EXTERNAL_PENDING), decision),
            "GCC AUCTION — OPPORTUNITÉ GCC — EXTERNE EN ATTENTE",
        )
        self.assertEqual(
            semantics.opportunity_title(_op(watcher.PATH_GCC_ONLY), decision),
            "GCC AUCTION — OPPORTUNITÉ GCC — EXTERNE NON CONFIRMÉ",
        )

    def test_pending_rewrites_ntfy_without_changing_valuation_path(self) -> None:
        op = _op(watcher.PATH_EXTERNAL_PENDING)
        decision = watcher.NotificationDecision(True, reasons=("nouvelle opportunité",))
        with patch.object(watcher, "NTFY_TOPIC", "test-topic"), patch.object(
            watcher.requests, "post", return_value=_OkResponse()
        ) as post:
            semantics.notify_with_external_confirmation_semantics(op, decision)

        kwargs = post.call_args.kwargs
        payload = kwargs["data"].decode("utf-8")
        self.assertTrue(payload.startswith("GCC AUCTION — OPPORTUNITÉ GCC — EXTERNE EN ATTENTE"))
        self.assertIn("Chemin de valorisation : EXTERNAL_PENDING", payload)
        self.assertIn("EXTERNE EN ATTENTE", kwargs["headers"]["Title"])
        self.assertEqual(op.valuation_path, watcher.PATH_EXTERNAL_PENDING)

    def test_final_alert_keeps_existing_title(self) -> None:
        op = _op(watcher.PATH_EXTERNAL_PENDING)
        decision = watcher.NotificationDecision(
            True, final_alert=True, reasons=("toujours sous le prix max dans les 5 dernières minutes",)
        )
        self.assertIsNone(semantics.opportunity_title(op, decision))


if __name__ == "__main__":
    unittest.main()
