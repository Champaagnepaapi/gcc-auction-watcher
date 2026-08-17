from __future__ import annotations

from pathlib import Path
import re
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
        for path in (
            "docs/project-capability-ledger.md",
            "docs/project-branch-inventory.md",
            "docs/project-open-pr-inventory.md",
            "docs/project-workflow-inventory.md",
            "docs/project-issue-inventory.md",
        ):
            self.assertIn(path, governance)
        self.assertIn("Mandatory capability-recovery check", governance)
        self.assertIn("Branch hygiene / deletion safety", governance)
        self.assertIn("Open PR hygiene", governance)
        self.assertIn("Issue hygiene", governance)
        self.assertIn("Workflow hygiene", governance)

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

    def test_open_pr_inventory_has_exactly_the_16_audited_open_prs(self):
        inventory = Path("docs/project-open-pr-inventory.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("exactement **16 PR ouvertes**", inventory)
        self.assertIn("**120 pull requests au total**", inventory)
        rows = [line for line in inventory.splitlines() if re.match(r"^\| #\d+ \|", line)]
        numbers = {
            int(re.match(r"^\| #(\d+) \|", line).group(1))
            for line in rows
        }
        self.assertEqual(
            numbers,
            {8, 54, 87, 92, 96, 106, 107, 108, 109, 110, 111, 113, 114, 115, 122, 123},
        )
        self.assertEqual(len(rows), 16)
        self.assertIn("#54", inventory)
        self.assertIn("SUPERSEDED / STALE_OPEN", inventory)
        self.assertIn("#87", inventory)
        self.assertIn("DEFERRED / BEHAVIOR_CHANGE", inventory)
        self.assertIn("#111", inventory)
        self.assertIn("#122", inventory)
        self.assertIn("#123", inventory)
        self.assertIn("V4_ILLIQUID_GCC_ONLY_MIN_UPSIDE_RATIO = 1.75", inventory)
        self.assertIn("V4_ILLIQUID_GCC_ONLY_MIN_ABSOLUTE_UPSIDE_EUR = 10", inventory)

    def test_workflow_inventory_separates_14_current_files_from_80_records(self):
        inventory = Path("docs/project-workflow-inventory.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("**14 fichiers workflow existent réellement", inventory)
        self.assertIn("**80 enregistrements de workflows**", inventory)
        self.assertIn("0ff115a95e8bbf8e4d04534e8efb343eb93cb128", inventory)
        self.assertIn("append-readme-pr65.yml", inventory)
        self.assertIn("fetch du fichier sur `main` retourne `404`", inventory)
        self.assertIn("v5-gcc-catalog-refresh.yml", inventory)
        self.assertIn("MAIN_SUPPORT / LEGACY_DEPENDENCY", inventory)

        raw_header = "Liste exhaustive 80/80 des chemins enregistrés :"
        raw = inventory.split(raw_header, 1)[1]
        code_block = raw.split("```text", 1)[1].split("```", 1)[0]
        names = [line.strip() for line in code_block.splitlines() if line.strip()]
        self.assertEqual(len(names), 80)
        self.assertEqual(len(set(names)), 80)
        for current in (
            "japan-edge-hunter.yml",
            "japan-edge-offline-validation.yml",
            "psa-api-diagnostic.yml",
            "robot-kb-cloud-shadow.yml",
            "robot-kb-sold-shadow.yml",
            "v4-auction-discovery-validation.yml",
            "v4-final-auction-check.yml",
            "v4-gcc-coverage-audit.yml",
            "v4-global-live-shadow.yml",
            "v4-global-shadow-dispatch-ci.yml",
            "v4-kb-shadow-ingest.yml",
            "v5-gcc-catalog-refresh.yml",
            "v5-live-raw-pipeline-diagnostic.yml",
            "watcher.yml",
        ):
            self.assertIn(current, names)

    def test_issue_inventory_has_exactly_the_three_repository_issues(self):
        inventory = Path("docs/project-issue-inventory.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("exactement **3 issues**", inventory)
        rows = [line for line in inventory.splitlines() if re.match(r"^\| #\d+ `", line)]
        numbers = {
            int(re.match(r"^\| #(\d+) `", line).group(1))
            for line in rows
        }
        self.assertEqual(numbers, {1, 28, 58})
        self.assertEqual(len(rows), 3)
        self.assertIn("ACTIVE_REGISTRY", inventory)
        self.assertIn("SUPERSEDED_BY_IMPLEMENTATION", inventory)
        self.assertIn("STALE_PLANNING_ISSUE", inventory)
        self.assertIn("#59/#60/#62/#68/#72/#75/#76", inventory)


if __name__ == "__main__":
    unittest.main()
