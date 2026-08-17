from __future__ import annotations

from pathlib import Path
import unittest


class V4CapabilityRecoveryWiringTests(unittest.TestCase):
    def test_tcgdex_recovery_layers_keep_proven_order(self):
        source = Path("run_watcher_multimarket.py").read_text(encoding="utf-8")
        markers = [
            "install_canonical_multimarket_pipeline()",
            "install_v4_tcgdex_exact_coordinate_recovery()",
            "install_v4_tcgdex_run1054_set_aliases()",
            "install_v4_tcgdex_generalized_coordinate_recovery()",
            "install_v4_tcgdex_two_of_three_backport()",
            "install_v4_tcgdex_unique_coordinate_fallback()",
            "install_multimarket_safety_hardening()",
        ]
        positions = [source.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))

    def test_capability_ledger_is_part_of_governance_startup(self):
        governance = Path(
            ".agents/rules/gcc-project-governance.md"
        ).read_text(encoding="utf-8")
        self.assertIn("docs/project-capability-ledger.md", governance)
        self.assertIn("Mandatory capability-recovery check", governance)

    def test_capability_ledger_records_shadow_not_as_production(self):
        ledger = Path("docs/project-capability-ledger.md").read_text(encoding="utf-8")
        self.assertIn("PR #108", ledger)
        self.assertIn("SHADOW/DEFERRED", ledger)
        self.assertIn("PR #8", ledger)
        self.assertIn("V5_ONLY", ledger)
        self.assertIn("PR #104", ledger)
        self.assertIn("DISABLED", ledger)


if __name__ == "__main__":
    unittest.main()
