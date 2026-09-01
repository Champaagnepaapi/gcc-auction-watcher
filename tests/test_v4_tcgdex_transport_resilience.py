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
    def setUp(self):
        resilience.reset_v4_tcgdex_run_breaker_for_tests()

    def tearDown(self):
        resilience.reset_v4_tcgdex_run_breaker_for_tests()

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

    def test_v4_run_breaker_opens_after_two_exhausted_logical_calls(self):
        logical = mock.Mock(side_effect=requests.ConnectionError("provider down"))
        url = f"{canonical.TCGDEX_BASE_URL}/ja/cards"

        with mock.patch.dict(os.environ, {"V4_TCGDEX_RUN_BREAKER_THRESHOLD": "2"}):
            with self.assertRaises(requests.ConnectionError):
                resilience._call_with_v4_run_breaker(logical, url, timeout=6)
            self.assertFalse(resilience._V4_RUN_OPEN)

            with self.assertRaises(requests.ConnectionError):
                resilience._call_with_v4_run_breaker(logical, url, timeout=6)
            self.assertTrue(resilience._V4_RUN_OPEN)

            with self.assertRaisesRegex(requests.ConnectionError, "run circuit open"):
                resilience._call_with_v4_run_breaker(logical, url, timeout=6)

        self.assertEqual(logical.call_count, 2)

    def test_real_provider_response_resets_v4_breaker_streak(self):
        logical = mock.Mock(
            side_effect=[
                requests.ConnectionError("first outage"),
                (404, {}, {}),
                requests.ConnectionError("second outage"),
                requests.ConnectionError("third outage"),
            ]
        )
        url = f"{canonical.TCGDEX_BASE_URL}/en/cards"

        with mock.patch.dict(os.environ, {"V4_TCGDEX_RUN_BREAKER_THRESHOLD": "2"}):
            with self.assertRaises(requests.ConnectionError):
                resilience._call_with_v4_run_breaker(logical, url, timeout=6)
            self.assertEqual(resilience._V4_CONSECUTIVE_EXHAUSTED, 1)

            result = resilience._call_with_v4_run_breaker(logical, url, timeout=6)
            self.assertEqual(result[0], 404)
            self.assertEqual(resilience._V4_CONSECUTIVE_EXHAUSTED, 0)

            with self.assertRaises(requests.ConnectionError):
                resilience._call_with_v4_run_breaker(logical, url, timeout=6)
            self.assertFalse(resilience._V4_RUN_OPEN)

            with self.assertRaises(requests.ConnectionError):
                resilience._call_with_v4_run_breaker(logical, url, timeout=6)
            self.assertTrue(resilience._V4_RUN_OPEN)

        self.assertEqual(logical.call_count, 4)

    def test_final_transient_http_counts_toward_v4_breaker(self):
        logical = mock.Mock(return_value=(503, {}, {}))
        url = f"{canonical.TCGDEX_BASE_URL}/fr/cards"

        with mock.patch.dict(os.environ, {"V4_TCGDEX_RUN_BREAKER_THRESHOLD": "2"}):
            first = resilience._call_with_v4_run_breaker(logical, url, timeout=6)
            second = resilience._call_with_v4_run_breaker(logical, url, timeout=6)
            self.assertEqual(first[0], 503)
            self.assertEqual(second[0], 503)
            self.assertTrue(resilience._V4_RUN_OPEN)
            with self.assertRaisesRegex(requests.ConnectionError, "run circuit open"):
                resilience._call_with_v4_run_breaker(logical, url, timeout=6)

        self.assertEqual(logical.call_count, 2)

    def test_non_tcgdex_request_is_untouched_even_when_v4_circuit_open(self):
        resilience._V4_RUN_OPEN = True
        original = mock.Mock(return_value=(200, {"provider": "other"}, {}))
        result = resilience._call_with_v4_run_breaker(
            original,
            "https://example.invalid/api",
            timeout=3,
        )
        self.assertEqual(result[0], 200)
        original.assert_called_once()

    def test_v4_installer_layers_run_breaker_after_global_wrapper_and_is_idempotent(self):
        old_json_get = canonical._json_get
        old_original = resilience._ORIGINAL_JSON_GET
        old_v4_original = resilience._V4_ORIGINAL_RESILIENT_JSON_GET
        fake = mock.Mock(return_value=(200, {}, {}))
        try:
            canonical._json_get = fake
            resilience._ORIGINAL_JSON_GET = None
            resilience._V4_ORIGINAL_RESILIENT_JSON_GET = None
            resilience.reset_v4_tcgdex_run_breaker_for_tests()

            resilience.install_v4_tcgdex_resilience()
            installed = canonical._json_get
            underlying = resilience._V4_ORIGINAL_RESILIENT_JSON_GET

            self.assertTrue(getattr(installed, "_v4_global_tcgdex_resilience", False))
            self.assertTrue(getattr(installed, "_v4_tcgdex_run_breaker", False))
            self.assertTrue(getattr(underlying, "_v4_global_tcgdex_resilience", False))
            self.assertIs(resilience._ORIGINAL_JSON_GET, fake)

            resilience.install_v4_tcgdex_resilience()
            self.assertIs(canonical._json_get, installed)
            self.assertIs(resilience._V4_ORIGINAL_RESILIENT_JSON_GET, underlying)
        finally:
            canonical._json_get = old_json_get
            resilience._ORIGINAL_JSON_GET = old_original
            resilience._V4_ORIGINAL_RESILIENT_JSON_GET = old_v4_original
            resilience.reset_v4_tcgdex_run_breaker_for_tests()

    def test_reset_helper_reopens_v4_circuit(self):
        resilience._V4_RUN_OPEN = True
        resilience._V4_CONSECUTIVE_EXHAUSTED = 4
        resilience.reset_v4_tcgdex_run_breaker_for_tests()
        self.assertFalse(resilience._V4_RUN_OPEN)
        self.assertEqual(resilience._V4_CONSECUTIVE_EXHAUSTED, 0)

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

    def test_production_workflow_routes_through_bootstrap_and_pins_breaker(self):
        workflow = (
            Path(__file__).resolve().parents[1] / ".github" / "workflows" / "watcher.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("python run_watcher_multimarket_resilient.py", workflow)
        self.assertNotIn("python run_watcher_multimarket.py\n", workflow)
        self.assertIn('V4_TCGDEX_RUN_BREAKER_THRESHOLD: "2"', workflow)


if __name__ == "__main__":
    unittest.main()
