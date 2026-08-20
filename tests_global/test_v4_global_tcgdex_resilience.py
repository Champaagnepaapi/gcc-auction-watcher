from __future__ import annotations

import os
import unittest
from unittest import mock

import requests

import v4_canonical_multimarket as canonical
import v4_global_tcgdex_resilience as resilience


class GlobalTcgdexResilienceTests(unittest.TestCase):
    def test_read_timeout_retries_once_then_returns_success(self):
        calls = []

        def fake(url, *, params=None, headers=None, timeout):
            calls.append(timeout)
            if len(calls) == 1:
                raise requests.ReadTimeout("slow")
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
                f"{canonical.TCGDEX_BASE_URL}/ja/cards",
                timeout=6,
            )

        self.assertEqual(result[0], 200)
        self.assertEqual(calls, [10.0, 10.0])

    def test_repeated_timeout_propagates_as_transient_error(self):
        calls = []

        def fake(url, *, params=None, headers=None, timeout):
            calls.append(timeout)
            raise requests.ReadTimeout("still slow")

        with mock.patch.dict(
            os.environ,
            {
                "GLOBAL_TCGDEX_MAX_ATTEMPTS": "2",
                "GLOBAL_TCGDEX_RETRY_BACKOFF_SECONDS": "0",
            },
        ):
            with self.assertRaises(requests.ReadTimeout):
                resilience._call_with_tcgdex_resilience(
                    fake,
                    f"{canonical.TCGDEX_BASE_URL}/ja/cards",
                    timeout=6,
                )

        self.assertEqual(len(calls), 2)

    def test_transient_503_retries_but_404_does_not(self):
        statuses = [503, 200]
        calls = []

        def transient(url, *, params=None, headers=None, timeout):
            calls.append(timeout)
            status = statuses.pop(0)
            return status, {}, {}

        with mock.patch.dict(os.environ, {"GLOBAL_TCGDEX_RETRY_BACKOFF_SECONDS": "0"}):
            result = resilience._call_with_tcgdex_resilience(
                transient,
                f"{canonical.TCGDEX_BASE_URL}/ja/cards",
                timeout=6,
            )
        self.assertEqual(result[0], 200)
        self.assertEqual(len(calls), 2)

        no_retry = mock.Mock(return_value=(404, {}, {}))
        result = resilience._call_with_tcgdex_resilience(
            no_retry,
            f"{canonical.TCGDEX_BASE_URL}/ja/cards",
            timeout=6,
        )
        self.assertEqual(result[0], 404)
        no_retry.assert_called_once()

    def test_non_tcgdex_request_is_untouched(self):
        original = mock.Mock(return_value=(200, {"provider": "other"}, {}))
        result = resilience._call_with_tcgdex_resilience(
            original,
            "https://example.invalid/api",
            timeout=3,
        )
        self.assertEqual(result[0], 200)
        self.assertEqual(original.call_args.kwargs["timeout"], 3)
        original.assert_called_once()

    def test_installer_is_idempotent(self):
        old_json_get = canonical._json_get
        old_original = resilience._ORIGINAL_JSON_GET
        fake = mock.Mock(return_value=(200, {}, {}))
        try:
            canonical._json_get = fake
            resilience._ORIGINAL_JSON_GET = None
            resilience.install_global_tcgdex_resilience()
            installed = canonical._json_get
            resilience.install_global_tcgdex_resilience()
            self.assertIs(canonical._json_get, installed)
            self.assertIs(resilience._ORIGINAL_JSON_GET, fake)
            self.assertTrue(getattr(installed, "_v4_global_tcgdex_resilience", False))
        finally:
            canonical._json_get = old_json_get
            resilience._ORIGINAL_JSON_GET = old_original


if __name__ == "__main__":
    unittest.main()
