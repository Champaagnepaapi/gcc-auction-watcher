from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

import watcher
import v4_ask_fallback_review as fallback
import v4_exact_active_ask_position as asks


class AskFallbackReviewTests(unittest.TestCase):
    def setUp(self):
        self.original_process = fallback._ORIGINAL_PROCESS
        fallback._ORIGINAL_PROCESS = lambda *args, **kwargs: []

    def tearDown(self):
        fallback._ORIGINAL_PROCESS = self.original_process

    @staticmethod
    def _lot(price: float = 60.0, source_type: str = "auction") -> watcher.Lot:
        return watcher.Lot(
            url="https://gradedcardcenter.com/item/test-card",
            title="PSA 9 Alakazam #1/102",
            current_price=price,
            source_type=source_type,
            grader="PSA",
            grade="9",
            card_set="Base Set",
            card_number="#1/102",
            language="English",
            minutes_to_end=5 if source_type == "auction" else None,
        )

    def test_exact_ask_can_emit_review_but_never_creates_sold_opportunity(self):
        lot = self._lot(60.0)
        candidate = SimpleNamespace(lot=lot)
        evidence = asks.ActiveAskEvidence(
            source="eBay BIN",
            price=100.0,
            url="https://www.ebay.fr/itm/example",
            title="PSA 9 Alakazam 1/102",
            gap_pct=40.0,
            gcc_is_cheapest=True,
        )
        state = {}
        now = datetime.now(timezone.utc)

        with mock.patch.dict(
            os.environ,
            {
                "V4_ASK_FALLBACK_HAIRCUT_PCT": "10",
                "V4_ASK_FALLBACK_MIN_DISCOUNT_PCT": "20",
                "V4_ASK_FALLBACK_MAX_CARDS_PER_RUN": "4",
            },
            clear=False,
        ), mock.patch.object(
            watcher, "commercial_identity_is_sufficient", return_value=True
        ), mock.patch.object(
            asks, "_cached_active_ask", return_value=None
        ), mock.patch.object(
            asks, "scrape_lowest_exact_ebay_ask", return_value=evidence
        ), mock.patch.object(
            asks, "_store_active_ask"
        ) as store, mock.patch.object(
            fallback, "_notify_review"
        ) as notify:
            result = fallback.process_with_exact_ask_fallback(
                object(), [candidate], state, object(), object(), now
            )

        self.assertEqual(result, [])
        store.assert_called_once()
        notify.assert_called_once()
        self.assertIn(fallback._STATE_KEY, state)
        # The lane remains review-only: it did not manufacture a ComparableSale.
        self.assertFalse(any(isinstance(item, watcher.ComparableSale) for item in result))

    def test_ask_too_close_does_not_notify(self):
        lot = self._lot(80.0)
        candidate = SimpleNamespace(lot=lot)
        evidence = asks.ActiveAskEvidence(
            source="eBay BIN",
            price=100.0,
            url="https://www.ebay.fr/itm/example",
            title="PSA 9 Alakazam 1/102",
            gap_pct=20.0,
            gcc_is_cheapest=True,
        )
        now = datetime.now(timezone.utc)

        with mock.patch.object(
            watcher, "commercial_identity_is_sufficient", return_value=True
        ), mock.patch.object(
            asks, "_cached_active_ask", return_value=evidence
        ), mock.patch.object(fallback, "_notify_review") as notify:
            fallback.process_with_exact_ask_fallback(
                object(), [candidate], {}, object(), object(), now
            )
        notify.assert_not_called()

    def test_identity_insufficient_never_spends_ask_lookup(self):
        lot = self._lot(50.0)
        candidate = SimpleNamespace(lot=lot)
        now = datetime.now(timezone.utc)

        with mock.patch.object(
            watcher, "commercial_identity_is_sufficient", return_value=False
        ), mock.patch.object(
            asks, "scrape_lowest_exact_ebay_ask"
        ) as scrape:
            fallback.process_with_exact_ask_fallback(
                object(), [candidate], {}, object(), object(), now
            )
        scrape.assert_not_called()


if __name__ == "__main__":
    unittest.main()
