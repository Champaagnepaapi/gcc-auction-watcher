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

    def test_recovery_docs_are_part_of_governance_startup(self):
        governance = Path(
            ".agents/rules/gcc-project-governance.md"
        ).read_text(encoding="utf-8")
        self.assertIn("docs/project-capability-ledger.md", governance)
        self.assertIn("docs/project-branch-inventory.md", governance)
        self.assertIn("Mandatory capability-recovery check", governance)
        self.assertIn("Branch hygiene / deletion safety", governance)

    def test_capability_ledger_records_shadow_not_as_production(self):
        ledger = Path("docs/project-capability-ledger.md").read_text(encoding="utf-8")
        self.assertIn("PR #108", ledger)
        self.assertIn("SHADOW/DEFERRED", ledger)
        self.assertIn("PR #8", ledger)
        self.assertIn("V5_ONLY", ledger)
        self.assertIn("PR #104", ledger)
        self.assertIn("DISABLED", ledger)

    def test_capability_ledger_preserves_recovered_foundations(self):
        ledger = Path("docs/project-capability-ledger.md").read_text(encoding="utf-8")
        for marker in (
            "chatgpt-gcc-cumulative-index-20260810",
            "agent/p0-card-knowledge-base-foundation",
            "agent/p1-shadow-observation-sidecar",
            "agent/p3-postgres-durable-shadow",
            "agent/kb-tcgdex-macro-cache",
            "agent/source-scout-ppt-cardinality-20260815",
            "agent/source-scout-tcgapi-identity-20260815",
            "agent/v4-robust-raw-consensus",
            "PR #115",
        ):
            self.assertIn(marker, ledger)

    def test_branch_inventory_has_all_145_audited_remote_names(self):
        inventory = Path("docs/project-branch-inventory.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("145/145", inventory)
        self.assertIn("agent/v5-poketrace-cardmarket-market-data", inventory)
        self.assertIn("fix/v4-recover-existing-capabilities-20260817", inventory)
        self.assertIn("agent/p0-card-knowledge-base-foundation", inventory)
        self.assertIn("agent/source-scout-benchmark-20260814", inventory)
        self.assertIn("feat/v4-global-multivault-edge-foundation", inventory)
        self.assertIn("tmp-noop-check", inventory)

        raw_header = "# 12. Contrôle de complétude — liste brute 145/145"
        raw = inventory.split(raw_header, 1)[1]
        code_block = raw.split("```text", 1)[1].split("```", 1)[0]
        names = [line.strip() for line in code_block.splitlines() if line.strip()]
        self.assertEqual(len(names), 145)
        self.assertEqual(len(set(names)), 145)
        self.assertIn("main", names)
        self.assertIn("oops-no-more", names)


if __name__ == "__main__":
    unittest.main()
