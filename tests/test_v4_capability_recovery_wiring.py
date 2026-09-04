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
            "install_v4_poketrace_market_retrieval()",
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
        for marker in (
            "SHADOW",
            "DEFERRED",
            "DISABLED",
            "V5_ONLY",
            "PR #8",
            "#108/#109/#110/#113/#114/#115/#138",
            "Capacités structurantes : #9, #50, #52, #104",
        ):
            self.assertIn(marker, ledger)
        self.assertIn("Supersessions / provenance", ledger)

    def test_capability_ledger_preserves_recovered_foundations(self):
        ledger = Path("docs/project-capability-ledger.md").read_text(encoding="utf-8")
        for marker in (
            "TCGdex / PokeTrace #119→#135",
            "fallback générique catalogue immuable",
            "#180 collecte Fanatics/COMC/Magi/Cardova",
            "#139 a réintégré/revalidé le stack historique",
            "GCC/Cardova/Magi/Fanatics/COMC",
            "PPT = `SOLD_AGGREGATED`",
            "PR #126 = `SUPERSEDED`",
        ):
            self.assertIn(marker, ledger)

    def test_branch_inventory_preserves_audited_provenance_without_fake_current_count(self):
        inventory = Path("docs/project-branch-inventory.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("dernier audit exhaustif", inventory)
        self.assertIn("158 branches distantes", inventory)
        self.assertIn("ne pas présenter `158` comme nombre actuel", inventory)
        for marker in (
            "agent/v5-poketrace-cardmarket-market-data",
            "feat/v4-global-marketplace-discovery-20260820",
            "ops/v4-global-marketplace-cutover-20260820",
            "ops/v4-global-run-registry-20260820",
            "shadow/v4-global-current-main-reintegration-20260819",
            "PR #126 : superseded",
            "Aucune branche n'a été supprimée",
        ):
            self.assertIn(marker, inventory)

    def test_open_pr_inventory_tracks_governance_surface_without_claiming_exhaustive_count(self):
        inventory = Path("docs/project-open-pr-inventory.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("PR ouvertes pertinentes pour la gouvernance courante", inventory)
        self.assertIn("ne pas utiliser ce document comme compteur exhaustif sans nouveau search live", inventory)
        rows = [line for line in inventory.splitlines() if re.match(r"^\| #\d+ \|", line)]
        numbers = {
            int(re.match(r"^\| #(\d+) \|", line).group(1))
            for line in rows
        }
        self.assertTrue({8, 54, 87, 92, 96, 106, 107, 126, 138, 141}.issubset(numbers))
        self.assertIn("STALE_OPEN/SUPERSEDED", inventory)
        self.assertIn("Décision produit V4 séparée/non déployée", inventory)
        self.assertIn("SUPERSEDED_BY_139", inventory)
        self.assertIn("SUPERSEDED_DIAGNOSTIC", inventory)
        self.assertIn("PR #8 reste explicitement protégée", inventory)

    def test_workflow_inventory_tracks_current_tree_and_historical_registry_distinction(self):
        inventory = Path("docs/project-workflow-inventory.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("**16 fichiers workflow YAML**", inventory)
        self.assertIn("L'API Actions peut conserver des records historiques", inventory)
        self.assertIn("le tree Git courant est l'autorité", inventory)
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
            "v4-global-market-offline-validation.yml",
            "v4-global-notify.yml",
            "v4-global-shadow-dispatch-ci.yml",
            "v4-kb-shadow-ingest.yml",
            "v5-gcc-catalog-refresh.yml",
            "v5-live-raw-pipeline-diagnostic.yml",
            "watcher.yml",
        ):
            self.assertIn(current, inventory)
        self.assertIn("Unique lane Global production", inventory)
        self.assertIn("aucune transaction", inventory)

    def test_issue_inventory_tracks_all_repository_issues_and_separate_registries(self):
        inventory = Path("docs/project-issue-inventory.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("exactement **5 issues uniques**", inventory)
        rows = [line for line in inventory.splitlines() if re.match(r"^\| #\d+ `", line)]
        numbers = {
            int(re.match(r"^\| #(\d+) `", line).group(1))
            for line in rows
        }
        self.assertEqual(numbers, {1, 28, 58, 150, 235})
        self.assertEqual(len(rows), 5)
        self.assertIn("V4_RUN_REGISTRY_ARCHIVE", inventory)
        self.assertIn("ACTIVE_V4_RUN_REGISTRY", inventory)
        self.assertIn("ACTIVE_GLOBAL_RUN_REGISTRY", inventory)
        self.assertIn("SUPERSEDED_BY_IMPLEMENTATION", inventory)
        self.assertIn("STALE_PLANNING_ISSUE", inventory)
        self.assertIn("#59/#60/#62/#68/#72/#75/#76", inventory)
        self.assertIn("Ne pas mélanger les runs Global dans #1", inventory)
        self.assertIn("Issue #235 — registre V4 actif", inventory)


if __name__ == "__main__":
    unittest.main()
