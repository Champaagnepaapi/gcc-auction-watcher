from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import unittest

import watcher
import v4_canonical_multimarket as multimarket
import v4_poketrace_aggregate_quality_guard as quality
import v4_poketrace_market_retrieval as retrieval


NOW = datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc)


def _lot() -> watcher.Lot:
    return watcher.Lot(
        url="https://gradedcardcenter.com/item/poketrace-quality-test",
        title="Charizard",
        current_price=75.0,
        source_type="fixed",
        grader="PSA",
        grade="9",
        card_number="4/102",
        card_set="Base Set",
        language="English",
    )


def _canonical() -> multimarket.CanonicalCard:
    return multimarket.CanonicalCard(
        "EXACT",
        card_id="base1-4",
        set_id="base1",
        set_name="Base Set",
        local_id="4",
        full_number="4/102",
        name="Charizard",
        language_code="en",
        reason="TCGDEX_EXACT_SET_LOCALID",
    )


def _estimate(low: float, central: float, high: float, *, sales: int = 29):
    return watcher.MarketEstimate(
        low=low,
        central=central,
        high=high,
        kept_comparables=[],
        rejected_outliers=[],
        recent_90_count=0,
        dated_count=0,
        liquidity="élevée",
        dispersion="faible",
        confidence="moyenne",
        adaptive_discount_pct=30.0,
        rationale=f"PokeTrace US eBay sold aggregate PSA_9, {sales} vente(s)",
        source_counts={"poketrace": sales},
        exact_grade_count=sales,
        same_grader_count=sales,
        source_consistent=True,
        grade_arbitrage=False,
    )


def _strong_evidence(low: float, central: float, high: float):
    return watcher.ExternalMarketEvidence(
        watcher.external_commercial_identity_key(_lot()),
        watcher.EXTERNAL_MATCHED,
        watcher.EVIDENCE_STRONG,
        "poketrace",
        estimate=_estimate(low, central, high),
        note="PokeTrace pt-test | PSA_9 | eBay sold agrégé | 29 vente(s) | EUR",
        fetched_at=NOW,
    )


class PokeTraceAggregateQualityGuardTests(unittest.TestCase):
    def setUp(self):
        self.original_evidence = retrieval._ORIGINAL_EVIDENCE
        self.original_base = quality._BASE_POKETRACE_EVIDENCE
        self.original_installed = quality._INSTALLED
        quality._BASE_POKETRACE_EVIDENCE = None
        quality._INSTALLED = False
        multimarket._DIAGNOSTICS = multimarket.MultiMarketDiagnostics()

    def tearDown(self):
        retrieval._ORIGINAL_EVIDENCE = self.original_evidence
        quality._BASE_POKETRACE_EVIDENCE = self.original_base
        quality._INSTALLED = self.original_installed

    def _install_fake(self, evidence):
        def fake_base(*_args, **_kwargs):
            if evidence.strength == watcher.EVIDENCE_STRONG:
                multimarket._DIAGNOSTICS.poketrace_strong += 1
            elif evidence.strength == watcher.EVIDENCE_WEAK:
                multimarket._DIAGNOSTICS.poketrace_weak += 1
            return evidence

        retrieval._ORIGINAL_EVIDENCE = fake_base
        quality.install_v4_poketrace_aggregate_quality_guard()

    def test_zero_width_strong_aggregate_is_not_actionable(self):
        self._install_fake(_strong_evidence(124.83, 124.83, 124.83))

        evidence = retrieval._structured_poketrace_evidence(
            _lot(), _canonical(), multimarket.RequestBudget(), NOW
        )

        self.assertEqual(evidence.status, watcher.EXTERNAL_CLEAN_INSUFFICIENT)
        self.assertEqual(evidence.strength, watcher.EVIDENCE_WEAK)
        self.assertIsNone(evidence.estimate)
        self.assertEqual(evidence.comparables, [])
        self.assertIn("agrégat PokeTrace dégénéré", evidence.note)
        self.assertIn("fallback APR/eBay requis", evidence.note)
        self.assertEqual(multimarket._DIAGNOSTICS.poketrace_strong, 0)
        self.assertEqual(multimarket._DIAGNOSTICS.poketrace_weak, 1)

    def test_real_price_range_remains_strong(self):
        original = _strong_evidence(95.0, 110.0, 132.0)
        self._install_fake(original)

        evidence = retrieval._structured_poketrace_evidence(
            _lot(), _canonical(), multimarket.RequestBudget(), NOW
        )

        self.assertIs(evidence, original)
        self.assertEqual(evidence.status, watcher.EXTERNAL_MATCHED)
        self.assertEqual(evidence.strength, watcher.EVIDENCE_STRONG)
        self.assertIsNotNone(evidence.estimate)
        self.assertEqual(multimarket._DIAGNOSTICS.poketrace_strong, 1)
        self.assertEqual(multimarket._DIAGNOSTICS.poketrace_weak, 0)

    def test_existing_weak_evidence_is_unchanged(self):
        weak = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(_lot()),
            watcher.EXTERNAL_CLEAN_INSUFFICIENT,
            watcher.EVIDENCE_WEAK,
            "poketrace",
            note="PokeTrace exact PSA_9: 2 vente(s)",
            fetched_at=NOW,
        )
        self._install_fake(weak)

        evidence = retrieval._structured_poketrace_evidence(
            _lot(), _canonical(), multimarket.RequestBudget(), NOW
        )

        self.assertIs(evidence, weak)
        self.assertEqual(multimarket._DIAGNOSTICS.poketrace_strong, 0)
        self.assertEqual(multimarket._DIAGNOSTICS.poketrace_weak, 1)

    def test_installer_is_idempotent(self):
        retrieval._ORIGINAL_EVIDENCE = lambda *_args, **_kwargs: _strong_evidence(
            95.0, 110.0, 132.0
        )
        quality.install_v4_poketrace_aggregate_quality_guard()
        first = retrieval._ORIGINAL_EVIDENCE
        quality.install_v4_poketrace_aggregate_quality_guard()
        self.assertIs(retrieval._ORIGINAL_EVIDENCE, first)
        self.assertIs(first, quality._quality_guarded_original_evidence)

    def test_production_bootstrap_installs_guard_before_canonical_runner(self):
        source = Path("run_watcher_multimarket_resilient.py").read_text(
            encoding="utf-8"
        )
        self.assertLess(
            source.index("install_v4_poketrace_aggregate_quality_guard()"),
            source.index('runpy.run_module("run_watcher_multimarket"'),
        )


if __name__ == "__main__":
    unittest.main()
