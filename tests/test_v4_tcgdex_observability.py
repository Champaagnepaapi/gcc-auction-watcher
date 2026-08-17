from __future__ import annotations

import unittest

import watcher
import v4_canonical_multimarket as multimarket
import v4_tcgdex_observability as observability


class TCGdexObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_process_external = watcher.process_external_market_candidates
        self.original_diagnostics_class = multimarket.MultiMarketDiagnostics
        self.original_diagnostics = multimarket._DIAGNOSTICS

    def tearDown(self) -> None:
        watcher.process_external_market_candidates = self.original_process_external
        multimarket.MultiMarketDiagnostics = self.original_diagnostics_class
        multimarket._DIAGNOSTICS = self.original_diagnostics

    def test_identity_counters_survive_external_stage_reset(self) -> None:
        diagnostics = multimarket.MultiMarketDiagnostics()
        diagnostics.tcgdex_attempted = 12
        diagnostics.tcgdex_exact = 7
        diagnostics.tcgdex_no_match = 3
        diagnostics.tcgdex_ambiguous = 1
        diagnostics.tcgdex_error = 1
        diagnostics.psa_below_8_excluded = 2
        diagnostics.psa_unsupported_grade_excluded = 1
        diagnostics.poketrace_attempted = 99
        diagnostics.raw_signal_found = 88
        multimarket._DIAGNOSTICS = diagnostics

        def fake_external_stage(*args, **kwargs):
            multimarket._DIAGNOSTICS = multimarket.MultiMarketDiagnostics()
            multimarket._DIAGNOSTICS.poketrace_attempted = 4
            multimarket._DIAGNOSTICS.raw_signal_found = 2
            return ["ok"]

        watcher.process_external_market_candidates = fake_external_stage
        observability.install_v4_tcgdex_observability()

        result = watcher.process_external_market_candidates()

        self.assertEqual(result, ["ok"])
        self.assertEqual(multimarket._DIAGNOSTICS.tcgdex_attempted, 12)
        self.assertEqual(multimarket._DIAGNOSTICS.tcgdex_exact, 7)
        self.assertEqual(multimarket._DIAGNOSTICS.tcgdex_no_match, 3)
        self.assertEqual(multimarket._DIAGNOSTICS.tcgdex_ambiguous, 1)
        self.assertEqual(multimarket._DIAGNOSTICS.tcgdex_error, 1)
        self.assertEqual(multimarket._DIAGNOSTICS.psa_below_8_excluded, 2)
        self.assertEqual(multimarket._DIAGNOSTICS.psa_unsupported_grade_excluded, 1)
        self.assertEqual(multimarket._DIAGNOSTICS.poketrace_attempted, 4)
        self.assertEqual(multimarket._DIAGNOSTICS.raw_signal_found, 2)
        self.assertIs(multimarket.MultiMarketDiagnostics, self.original_diagnostics_class)

    def test_diagnostics_class_is_restored_when_external_stage_raises(self) -> None:
        diagnostics = multimarket.MultiMarketDiagnostics()
        diagnostics.tcgdex_attempted = 5
        multimarket._DIAGNOSTICS = diagnostics

        def failing_external_stage(*args, **kwargs):
            multimarket._DIAGNOSTICS = multimarket.MultiMarketDiagnostics()
            raise RuntimeError("provider failure")

        watcher.process_external_market_candidates = failing_external_stage
        observability.install_v4_tcgdex_observability()

        with self.assertRaisesRegex(RuntimeError, "provider failure"):
            watcher.process_external_market_candidates()

        self.assertEqual(multimarket._DIAGNOSTICS.tcgdex_attempted, 5)
        self.assertIs(multimarket.MultiMarketDiagnostics, self.original_diagnostics_class)

    def test_installer_is_idempotent(self) -> None:
        def fake_external_stage(*args, **kwargs):
            return []

        watcher.process_external_market_candidates = fake_external_stage
        observability.install_v4_tcgdex_observability()
        first_wrapper = watcher.process_external_market_candidates
        observability.install_v4_tcgdex_observability()

        self.assertIs(watcher.process_external_market_candidates, first_wrapper)


if __name__ == "__main__":
    unittest.main()
