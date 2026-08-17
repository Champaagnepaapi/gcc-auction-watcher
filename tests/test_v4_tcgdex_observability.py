from __future__ import annotations

from pathlib import Path
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

    def test_reinstall_after_downstream_replacement_wraps_current_processor(self) -> None:
        diagnostics = multimarket.MultiMarketDiagnostics()
        diagnostics.tcgdex_attempted = 9
        diagnostics.tcgdex_exact = 6
        multimarket._DIAGNOSTICS = diagnostics

        def initial_external_stage(*args, **kwargs):
            multimarket._DIAGNOSTICS = multimarket.MultiMarketDiagnostics()
            return ["initial"]

        watcher.process_external_market_candidates = initial_external_stage
        observability.install_v4_tcgdex_observability()
        first_wrapper = watcher.process_external_market_candidates

        # Reproduce the production failure from run #1032: a downstream installer
        # replaces the external processor after observability was already installed.
        def downstream_replacement(*args, **kwargs):
            multimarket._DIAGNOSTICS = multimarket.MultiMarketDiagnostics()
            multimarket._DIAGNOSTICS.poketrace_attempted = 3
            return ["downstream"]

        watcher.process_external_market_candidates = downstream_replacement
        observability.install_v4_tcgdex_observability()
        final_wrapper = watcher.process_external_market_candidates

        self.assertIsNot(final_wrapper, downstream_replacement)
        self.assertIsNot(final_wrapper, first_wrapper)
        self.assertEqual(final_wrapper(), ["downstream"])
        self.assertEqual(multimarket._DIAGNOSTICS.tcgdex_attempted, 9)
        self.assertEqual(multimarket._DIAGNOSTICS.tcgdex_exact, 6)
        self.assertEqual(multimarket._DIAGNOSTICS.poketrace_attempted, 3)

    def test_production_bootstrap_finalizes_observability_after_multimarket_safety(self) -> None:
        entrypoint = Path(__file__).resolve().parents[1] / "run_watcher_multimarket.py"
        source = entrypoint.read_text(encoding="utf-8")
        main_block = source.split('if __name__ == "__main__":', 1)[1]

        safety_pos = main_block.index("install_multimarket_safety_hardening()")
        observability_pos = main_block.index("install_v4_tcgdex_observability()")

        self.assertLess(safety_pos, observability_pos)
        self.assertEqual(main_block.count("install_v4_tcgdex_observability()"), 1)


if __name__ == "__main__":
    unittest.main()
