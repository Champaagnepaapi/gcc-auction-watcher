from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest import mock

import requests

import v4_canonical_multimarket as canonical
import v4_global_tcgdex_resilience as resilience
import run_watcher_multimarket_resilient as bootstrap


class V4TcgdexTransportResilienceTests(unittest.TestCase):
    def test_v4_alias_reuses_proven_global_installer(self):
        with mock.patch.object(resilience, "install_global_tcgdex_resilience") as delegate:
            resilience.install_v4_tcgdex_resilience()
        delegate.assert_called_once_with()

    def test_v4_timeout_uses_proven_10s_floor_and_one_retry(self):
        calls: list[float] = []

        def fake(url, *, params=None, headers=None, timeout):
            calls.append(float(timeout))
            if len(calls) == 1:
                raise requests.ConnectionError("transient")
            return 200, {"ok": True}, {}

        with mock.patch.dict(
            os.environ,
            {
                "GLOBAL_TCGDEX_MAX_ATTEMPTS": "2",
                "GLOBAL_TCGDEX_REQUEST_TIMEOUT_SECONDS": "10",
                "GLOBAL_TCGDEX_RETRY_BACKOFF_SECONDS": "0",
            },
        ):
            result = resilience._call_with_tcgdex_resilience(
                fake,
                f"{canonical.TCGDEX_BASE_URL}/fr/cards",
                timeout=6,
            )

        self.assertEqual(result[0], 200)
        self.assertEqual(calls, [10.0, 10.0])

    def test_exhausted_connection_errors_still_propagate_fail_closed(self):
        calls = 0

        def fake(url, *, params=None, headers=None, timeout):
            nonlocal calls
            calls += 1
            raise requests.ConnectionError("still unavailable")

        with mock.patch.dict(
            os.environ,
            {
                "GLOBAL_TCGDEX_MAX_ATTEMPTS": "2",
                "GLOBAL_TCGDEX_RETRY_BACKOFF_SECONDS": "0",
            },
        ):
            with self.assertRaises(requests.ConnectionError):
                resilience._call_with_tcgdex_resilience(
                    fake,
                    f"{canonical.TCGDEX_BASE_URL}/ja/cards",
                    timeout=6,
                )

        self.assertEqual(calls, 2)

    def test_clean_404_is_not_retried_or_reclassified(self):
        original = mock.Mock(return_value=(404, {}, {}))
        result = resilience._call_with_tcgdex_resilience(
            original,
            f"{canonical.TCGDEX_BASE_URL}/en/cards",
            timeout=6,
        )
        self.assertEqual(result[0], 404)
        original.assert_called_once()

    def test_bootstrap_installs_resilience_before_canonical_runner(self):
        order: list[str] = []

        with mock.patch.object(
            bootstrap,
            "install_v4_tcgdex_resilience",
            side_effect=lambda: order.append("resilience"),
        ), mock.patch.object(
            bootstrap.runpy,
            "run_module",
            side_effect=lambda *args, **kwargs: order.append("runner"),
        ) as run_module:
            bootstrap.main()

        self.assertEqual(order, ["resilience", "runner"])
        run_module.assert_called_once_with(
            "run_watcher_multimarket",
            run_name="__main__",
            alter_sys=True,
        )

    def test_production_workflow_routes_only_main_scanner_through_bootstrap(self):
        workflow = (
            Path(__file__).resolve().parents[1] / ".github" / "workflows" / "watcher.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("python run_watcher_multimarket_resilient.py", workflow)
        self.assertNotIn("python run_watcher_multimarket.py\n", workflow)


if __name__ == "__main__":
    unittest.main()
