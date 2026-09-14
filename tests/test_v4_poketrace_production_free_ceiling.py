from __future__ import annotations

import unittest
from pathlib import Path


CEILING = 'os.environ.setdefault("V4_POKETRACE_PLAN_CEILING", "FREE")'


class PokeTraceProductionFreeCeilingTests(unittest.TestCase):
    def _assert_ceiling_before_provider_imports(self, path: str, first_provider_import: str) -> None:
        text = Path(path).read_text(encoding="utf-8")
        self.assertIn("import os", text)
        self.assertIn(CEILING, text)
        self.assertLess(text.index(CEILING), text.index(first_provider_import))

    def test_main_scanner_defaults_to_free_before_provider_imports(self):
        self._assert_ceiling_before_provider_imports(
            "run_watcher_multimarket_resilient.py",
            "import v4_pricecharting_valuation",
        )

    def test_global_runner_defaults_to_free_before_provider_imports(self):
        self._assert_ceiling_before_provider_imports(
            "v4_global_marketplace_notify_resilient.py",
            "import v4_global_live_confirmed",
        )

    def test_pr_validation_keeps_explicit_free_ceiling(self):
        workflow = Path(
            ".github/workflows/v4-global-market-offline-validation.yml"
        ).read_text(encoding="utf-8")
        self.assertIn('V4_POKETRACE_PLAN_CEILING: "FREE"', workflow)


if __name__ == "__main__":
    unittest.main()
