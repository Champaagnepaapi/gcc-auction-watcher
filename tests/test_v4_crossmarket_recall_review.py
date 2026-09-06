from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

import watcher
import v4_canonical_multimarket as multimarket
import v4_crossmarket_recall_review as review


class CrossMarketRecallReviewTests(unittest.TestCase):
    def setUp(self):
        self.original_process = review._ORIGINAL_PROCESS
        self.original_poketrace = review._ORIGINAL_POKETRACE
        review._ORIGINAL_PROCESS = lambda *args, **kwargs: []

    def tearDown(self):
        review._ORIGINAL_PROCESS = self.original_process
        review._ORIGINAL_POKETRACE = self.original_poketrace

    @staticmethod
    def _lot() -> watcher.Lot:
        return watcher.Lot(
            url="https://gradedcardcenter.com/item/alakazam",
            title="PCA 9.5 Alakazam",
            current_price=50.0,
            source_type="auction",
            grader="PCA",
            grade="9.5",
            card_set="Set de base",
            card_number="#1/102",
            language="French",
            minutes_to_end=5,
        )

    def test_half_grade_uses_lower_psa_reference_not_synthetic_9_5(self):
        self.assertEqual(review._reference_psa_grade(9.5), 9.0)
        self.assertEqual(review._reference_psa_grade(8.5), 8.0)
        self.assertEqual(review._reference_psa_grade(10.0), 10.0)

    def test_english_bridge_requires_same_tcgdex_card_set_and_localid(self):
        lot = self._lot()
        canonical = multimarket.CanonicalCard(
            status="EXACT",
            card_id="base1-1",
            set_id="base1",
            set_name="Set de base",
            local_id="1",
            full_number="1/102",
            name="Alakazam",
            language_code="fr",
            reason="TCGDEX_EXACT_SET_LOCALID",
        )
        detail = {
            "id": "base1-1",
            "localId": "1",
            "name": "Alakazam",
            "set": {"id": "base1", "name": "Base Set"},
        }
        with mock.patch.object(
            multimarket, "_fetch_tcgdex_card_detail", return_value=(200, detail)
        ):
            bridged = review._english_bridge(lot, canonical)
        self.assertIsNotNone(bridged)
        proxy_lot, proxy_canonical, cross_language = bridged
        self.assertTrue(cross_language)
        self.assertEqual(proxy_lot.language, "English")
        self.assertEqual(proxy_canonical.card_id, canonical.card_id)
        self.assertEqual(proxy_canonical.set_id, canonical.set_id)
        self.assertEqual(proxy_canonical.local_id, canonical.local_id)

    def test_english_bridge_rejects_set_conflict(self):
        lot = self._lot()
        canonical = multimarket.CanonicalCard(
            status="EXACT",
            card_id="base1-1",
            set_id="base1",
            set_name="Set de base",
            local_id="1",
            full_number="1/102",
            name="Alakazam",
            language_code="fr",
        )
        detail = {
            "id": "base1-1",
            "localId": "1",
            "name": "Alakazam",
            "set": {"id": "wrong-set", "name": "Wrong"},
        }
        with mock.patch.object(
            multimarket, "_fetch_tcgdex_card_detail", return_value=(200, detail)
        ):
            self.assertIsNone(review._english_bridge(lot, canonical))

    def test_crossmarket_reference_emits_review_only_and_preserves_delegate_result(self):
        lot = self._lot()
        candidate = SimpleNamespace(lot=lot)
        canonical = multimarket.CanonicalCard(
            status="EXACT",
            card_id="base1-1",
            set_id="base1",
            set_name="Set de base",
            local_id="1",
            full_number="1/102",
            name="Alakazam",
            language_code="fr",
        )
        estimate = watcher.MarketEstimate(
            low=120.0,
            central=120.0,
            high=120.0,
            kept_comparables=[],
            rejected_outliers=[],
            recent_90_count=0,
            dated_count=0,
            liquidity="élevée",
            dispersion="faible",
            confidence="moyenne",
            adaptive_discount_pct=25.0,
            rationale="PokeTrace PSA aggregate",
            source_counts={"poketrace": 100},
            exact_grade_count=100,
            same_grader_count=100,
        )
        evidence = watcher.ExternalMarketEvidence(
            identity_key="proxy",
            status=watcher.EXTERNAL_MATCHED,
            strength=watcher.EVIDENCE_STRONG,
            source="poketrace",
            estimate=estimate,
        )
        state = {}
        now = datetime.now(timezone.utc)

        with mock.patch.object(multimarket, "POKETRACE_ENABLED", True), \
             mock.patch.object(multimarket, "POKETRACE_API_KEY", "test"), \
             mock.patch.object(multimarket, "_canonical_from_lot", return_value=canonical), \
             mock.patch.object(
                 review,
                 "_reference_evidence",
                 return_value=(evidence, 9.0, True, True),
             ), \
             mock.patch.object(review, "_notify") as notify:
            result = review._process_delegate(
                object(), [candidate], state, object(), object(), now
            )

        self.assertEqual(result, [])
        notify.assert_called_once()
        self.assertIn(review._STATE_KEY, state)


if __name__ == "__main__":
    unittest.main()
