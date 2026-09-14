from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest import mock

import v4_global_fanatics_native_identity as v1
import v4_global_marketplace_fanatics_provider_language as provider


class FanaticsRejectionDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        provider._fanatics_diagnostics_count = 0

    def test_production_is_inert_without_explicit_opt_in(self):
        resolution = v1.FanaticsNativeResolution("NO_MATCH", "explicit_language_unproven")
        output = io.StringIO()
        with mock.patch.dict(os.environ, {"GITHUB_EVENT_NAME": "workflow_dispatch"}, clear=True):
            with redirect_stdout(output):
                provider._emit_fanatics_diagnostic(
                    title="2025 Pokémon Pikachu #25 PSA 10",
                    url="https://www.fanaticscollect.com/buy-now/example",
                    proof_text="public provider body",
                    resolution=resolution,
                )
        self.assertEqual(output.getvalue(), "")

    def test_pull_request_logs_public_listing_reason_without_changing_resolution(self):
        resolution = v1.FanaticsNativeResolution("NO_MATCH", "explicit_language_unproven")
        output = io.StringIO()
        with mock.patch.dict(os.environ, {"GITHUB_EVENT_NAME": "pull_request"}, clear=True):
            with redirect_stdout(output):
                provider._emit_fanatics_diagnostic(
                    title="2025 Pokémon Pikachu #25 PSA 10",
                    url="https://www.fanaticscollect.com/buy-now/example",
                    proof_text="public provider body",
                    resolution=resolution,
                )
        text = output.getvalue()
        self.assertIn("[FANATICS_DIAG]", text)
        self.assertIn("status=NO_MATCH", text)
        self.assertIn("reason=explicit_language_unproven", text)
        self.assertIn("provider_language=none", text)
        self.assertIn("url=https://www.fanaticscollect.com/buy-now/example", text)
        self.assertEqual(resolution.status, "NO_MATCH")

    def test_short_h1_language_is_diagnostic_and_explicit(self):
        title = "2025 Pokémon Destined Rivals EN #193 PSA 10"
        self.assertEqual(provider._short_title_language(title), ("en", "English"))
        self.assertEqual(provider._provider_language("", title=title), ("en", "English"))

    def test_diagnostics_are_bounded(self):
        resolution = v1.FanaticsNativeResolution("NO_MATCH", "tcgdex_no_exact")
        provider._fanatics_diagnostics_count = provider._FANATICS_DIAGNOSTICS_MAX
        output = io.StringIO()
        with mock.patch.dict(os.environ, {"GITHUB_EVENT_NAME": "pull_request"}, clear=True):
            with redirect_stdout(output):
                provider._emit_fanatics_diagnostic(
                    title="2025 Pokémon English Pikachu #25 PSA 10",
                    url="https://www.fanaticscollect.com/buy-now/example",
                    proof_text="English",
                    resolution=resolution,
                )
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
