from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

import watcher
import v4_canonical_multimarket as multimarket
import v4_crossmarket_recall_review as review
import v4_pricecharting_valuation as pricecharting


def _evidence(
    central: float,
    *,
    source: str = "poketrace",
    count: int = 20,
    strength: str = watcher.EVIDENCE_STRONG,
) -> watcher.ExternalMarketEvidence:
    estimate = watcher.MarketEstimate(
        low=central,
        central=central,
        high=central,
        kept_comparables=[],
        rejected_outliers=[],
        recent_90_count=0,
        dated_count=0,
        liquidity="élevée",
        dispersion="faible",
        confidence="moyenne",
        adaptive_discount_pct=25.0,
        rationale=f"{source} aggregate",
        source_counts={source: count},
        exact_grade_count=count,
        same_grader_count=count,
    )
    return watcher.ExternalMarketEvidence(
        identity_key="proxy",
        status=watcher.EXTERNAL_MATCHED,
        strength=strength,
        source=source,
        estimate=estimate,
    )


def _unavailable(source: str = "poketrace") -> watcher.ExternalMarketEvidence:
    return watcher.ExternalMarketEvidence(
        identity_key="proxy",
        status=watcher.EXTERNAL_CLEAN_NO_MATCH,
        strength=watcher.EVIDENCE_UNAVAILABLE,
        source=source,
    )


class CrossMarketRecallReviewTests(unittest.TestCase):
    def setUp(self):
        self.original_process = review._ORIGINAL_PROCESS
        self.original_poketrace = review._ORIGINAL_POKETRACE
        review._ORIGINAL_PROCESS = lambda *args, **kwargs: []

    def tearDown(self):
        review._ORIGINAL_PROCESS = self.original_process
        review._ORIGINAL_POKETRACE = self.original_poketrace

    @staticmethod
    def _lot(
        *,
        grader: str = "PCA",
        grade: str = "9.5",
        language: str = "Japanese",
        price: float = 15.0,
        title: str = "Eevee ex",
        number: str = "#126/187",
        card_set: str = "Terastal Fest ex",
    ) -> watcher.Lot:
        return watcher.Lot(
            url=f"https://gradedcardcenter.com/item/{title.lower().replace(' ', '-')}",
            title=title,
            current_price=price,
            source_type="fixed",
            grader=grader,
            grade=grade,
            card_set=card_set,
            card_number=number,
            language=language,
        )

    @staticmethod
    def _canonical(*, language_code: str = "ja") -> multimarket.CanonicalCard:
        return multimarket.CanonicalCard(
            status="EXACT",
            card_id="sv8a-126",
            set_id="sv8a",
            set_name="Terastal Fest ex",
            local_id="126",
            full_number="126/187",
            name="Eevee ex",
            language_code=language_code,
            reason="TCGDEX_EXACT_SET_LOCALID",
        )

    def test_psa_helper_never_synthesizes_psa_9_5(self):
        self.assertEqual(review._reference_psa_grade(9.5), 9.0)
        self.assertEqual(review._reference_psa_grade(8.5), 8.0)
        self.assertEqual(review._reference_psa_grade(10.0), 10.0)

    def test_english_bridge_requires_same_tcgdex_card_set_and_localid(self):
        lot = self._lot(language="French")
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
        lot = self._lot(language="French")
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

    def test_pca_9_5_probes_cgc_and_bgs_same_grade_never_psa_9(self):
        lot = self._lot(grader="PCA", grade="9.5")
        canonical = self._canonical()
        calls = []

        def provider(proxy_lot, _canonical, _budget, _now):
            calls.append((proxy_lot.grader, proxy_lot.grade))
            if proxy_lot.grader == "CGC":
                return _evidence(18.0)
            if proxy_lot.grader == "BGS":
                return _evidence(16.0)
            return _unavailable()

        review._ORIGINAL_POKETRACE = provider
        with mock.patch.object(
            pricecharting, "pricecharting_evidence_for_lot"
        ) as pc:
            result = review._reference_evidence(
                lot, canonical, multimarket.RequestBudget(), datetime.now(timezone.utc)
            )

        self.assertIsNotNone(result)
        self.assertEqual(result.reference_grader, "BGS")
        self.assertEqual(result.reference_grade, 9.5)
        self.assertEqual(result.basis, "SAME_GRADE_SECONDARY_PROXY")
        self.assertEqual(result.raw_reference_eur, 16.0)
        self.assertEqual(calls, [("CGC", "9.5"), ("BGS", "9.5")])
        pc.assert_not_called()

    def test_pca_9_5_without_same_grade_proxy_fails_closed_no_psa9(self):
        lot = self._lot(grader="PCA", grade="9.5")
        canonical = self._canonical()
        calls = []

        def provider(proxy_lot, _canonical, _budget, _now):
            calls.append((proxy_lot.grader, proxy_lot.grade))
            return _unavailable()

        review._ORIGINAL_POKETRACE = provider
        result = review._reference_evidence(
            lot, canonical, multimarket.RequestBudget(), datetime.now(timezone.utc)
        )
        self.assertIsNone(result)
        self.assertEqual(calls, [("CGC", "9.5"), ("BGS", "9.5")])
        self.assertNotIn(("PSA", "9"), calls)

    def test_ca10_prefers_cgc10_same_grade_proxy(self):
        lot = self._lot(grader="CA", grade="10", price=18.0)
        canonical = self._canonical()
        calls = []

        def provider(proxy_lot, _canonical, _budget, _now):
            calls.append((proxy_lot.grader, proxy_lot.grade))
            if proxy_lot.grader == "CGC":
                return _evidence(22.0)
            return _evidence(35.0)

        review._ORIGINAL_POKETRACE = provider
        with mock.patch.object(
            pricecharting,
            "pricecharting_evidence_for_lot",
            return_value=_unavailable("pricecharting"),
        ):
            result = review._reference_evidence(
                lot, canonical, multimarket.RequestBudget(), datetime.now(timezone.utc)
            )

        self.assertIsNotNone(result)
        self.assertEqual(result.reference_grader, "CGC")
        self.assertEqual(result.reference_grade, 10.0)
        self.assertEqual(result.basis, "SAME_GRADE_SECONDARY_PROXY")
        self.assertEqual(result.raw_reference_eur, 22.0)
        self.assertEqual(calls, [("CGC", "10")])
        self.assertNotIn(("PSA", "10"), calls)

    def test_ca10_psa_fallback_is_pricecharting_capped_and_haircut_35(self):
        lot = self._lot(grader="CA", grade="10", price=18.0)
        canonical = self._canonical()

        def provider(proxy_lot, _canonical, _budget, _now):
            if proxy_lot.grader == "CGC":
                return _unavailable()
            if proxy_lot.grader == "PSA":
                return _evidence(40.0)
            return _unavailable()

        review._ORIGINAL_POKETRACE = provider
        with mock.patch.object(
            pricecharting,
            "pricecharting_evidence_for_lot",
            return_value=_evidence(34.0, source="pricecharting"),
        ):
            result = review._reference_evidence(
                lot, canonical, multimarket.RequestBudget(), datetime.now(timezone.utc)
            )

        self.assertIsNotNone(result)
        self.assertEqual(result.reference_grader, "PSA")
        self.assertEqual(result.basis, "PSA_FALLBACK_CONSERVATIVE")
        self.assertEqual(result.raw_reference_eur, 34.0)
        self.assertEqual(result.pricecharting_guide_eur, 34.0)
        self.assertEqual(
            review._cross_grader_haircut("CA", result.basis),
            35.0,
        )

    def test_cross_grader_review_floor_is_30_but_cross_language_only_keeps_base(self):
        with mock.patch.dict(
            review.os.environ,
            {"V4_CROSSMARKET_REVIEW_MIN_DISCOUNT_PCT": "20"},
            clear=False,
        ):
            self.assertEqual(
                review._required_review_discount(cross_grader=True),
                30.0,
            )
            self.assertEqual(
                review._required_review_discount(cross_grader=False),
                20.0,
            )

    def test_glaceon_like_ca10_psa_minus_20_false_alert_is_suppressed(self):
        lot = self._lot(
            grader="CA",
            grade="10",
            price=18.0,
            title="Glaceon ex",
            number="#041/187",
        )
        candidate = SimpleNamespace(lot=lot)
        result = review.ReferenceResult(
            evidence=_evidence(34.37, count=120),
            reference_grader="PSA",
            reference_grade=10.0,
            cross_grader=True,
            cross_language=False,
            basis="PSA_FALLBACK_CONSERVATIVE",
            raw_reference_eur=34.37,
        )
        state = {}
        now = datetime.now(timezone.utc)

        with mock.patch.object(multimarket, "POKETRACE_ENABLED", True), \
             mock.patch.object(multimarket, "POKETRACE_API_KEY", "test"), \
             mock.patch.object(
                 multimarket, "_canonical_from_lot", return_value=self._canonical()
             ), \
             mock.patch.object(review, "_reference_evidence", return_value=result), \
             mock.patch.object(review, "_notify") as notify:
            returned = review._process_delegate(
                object(), [candidate], state, object(), object(), now
            )

        self.assertEqual(returned, [])
        notify.assert_not_called()
        self.assertNotIn(review._STATE_KEY, state)

    def test_riolu_like_ca10_psa_fallback_is_suppressed(self):
        lot = self._lot(
            grader="CA",
            grade="10",
            price=21.0,
            title="Riolu",
            number="#068/063",
            card_set="Mega Brave",
        )
        candidate = SimpleNamespace(lot=lot)
        result = review.ReferenceResult(
            evidence=_evidence(36.14, count=212),
            reference_grader="PSA",
            reference_grade=10.0,
            cross_grader=True,
            cross_language=False,
            basis="PSA_FALLBACK_CONSERVATIVE",
            raw_reference_eur=36.14,
        )
        state = {}
        now = datetime.now(timezone.utc)

        with mock.patch.object(multimarket, "POKETRACE_ENABLED", True), \
             mock.patch.object(multimarket, "POKETRACE_API_KEY", "test"), \
             mock.patch.object(
                 multimarket, "_canonical_from_lot", return_value=self._canonical()
             ), \
             mock.patch.object(review, "_reference_evidence", return_value=result), \
             mock.patch.object(review, "_notify") as notify:
            review._process_delegate(
                object(), [candidate], state, object(), object(), now
            )

        notify.assert_not_called()
        self.assertNotIn(review._STATE_KEY, state)

    def test_ca10_psa_35_recall_can_emit_when_45_would_have_missed(self):
        lot = self._lot(grader="CA", grade="10", price=16.0, title="Recall edge")
        candidate = SimpleNamespace(lot=lot)
        result = review.ReferenceResult(
            evidence=_evidence(40.0, count=40),
            reference_grader="PSA",
            reference_grade=10.0,
            cross_grader=True,
            cross_language=False,
            basis="PSA_FALLBACK_CONSERVATIVE",
            raw_reference_eur=40.0,
        )
        state = {}
        now = datetime.now(timezone.utc)

        with mock.patch.object(multimarket, "POKETRACE_ENABLED", True), \
             mock.patch.object(multimarket, "POKETRACE_API_KEY", "test"), \
             mock.patch.object(
                 multimarket, "_canonical_from_lot", return_value=self._canonical()
             ), \
             mock.patch.object(review, "_reference_evidence", return_value=result), \
             mock.patch.object(review, "_notify") as notify:
            review._process_delegate(
                object(), [candidate], state, object(), object(), now
            )

        # 35% haircut => reference 26 EUR => 38.5% discount: review emits.
        # 45% haircut would yield 22 EUR => 27.3%: below the 30% review floor.
        notify.assert_called_once()
        self.assertIn(review._STATE_KEY, state)

    def test_strong_same_grade_proxy_edge_can_still_emit_review_and_store_v2_state(self):
        lot = self._lot(grader="PCA", grade="9.5", price=10.0)
        candidate = SimpleNamespace(lot=lot)
        result = review.ReferenceResult(
            evidence=_evidence(25.0, count=20),
            reference_grader="BGS",
            reference_grade=9.5,
            cross_grader=True,
            cross_language=False,
            basis="SAME_GRADE_SECONDARY_PROXY",
            raw_reference_eur=25.0,
        )
        state = {}
        now = datetime.now(timezone.utc)

        with mock.patch.object(multimarket, "POKETRACE_ENABLED", True), \
             mock.patch.object(multimarket, "POKETRACE_API_KEY", "test"), \
             mock.patch.object(
                 multimarket, "_canonical_from_lot", return_value=self._canonical()
             ), \
             mock.patch.object(review, "_reference_evidence", return_value=result), \
             mock.patch.object(review, "_notify") as notify:
            returned = review._process_delegate(
                object(), [candidate], state, object(), object(), now
            )

        self.assertEqual(returned, [])
        notify.assert_called_once()
        root = state[review._STATE_KEY]
        self.assertEqual(root["schema_version"], 2)
        entry = next(iter(root["entries"].values()))
        self.assertEqual(entry["basis"], "SAME_GRADE_SECONDARY_PROXY")

    def test_old_v1_state_does_not_suppress_v2_recalibration(self):
        lot = self._lot()
        state = {
            review._STATE_KEY: {
                "schema_version": 1,
                "entries": {review._state_key(lot): {"notified_at": "old"}},
            }
        }
        self.assertFalse(review._already_sent(state, lot))


if __name__ == "__main__":
    unittest.main()
