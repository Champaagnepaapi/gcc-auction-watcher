import json
import subprocess
import unittest
from unittest.mock import Mock, patch

import v4_ebay_hard_timeout_isolation as isolation
import watcher


class _SuccessfulProcess:
    def __init__(self, stdout):
        self.pid = 1234
        self.returncode = 0
        self._stdout = stdout
        self.communicate_calls = 0

    def communicate(self, payload=None, timeout=None):
        self.communicate_calls += 1
        return self._stdout, ""


class _HungProcess:
    def __init__(self):
        self.pid = 4321
        self.returncode = None
        self.communicate_calls = 0
        self.killed = False

    def communicate(self, payload=None, timeout=None):
        self.communicate_calls += 1
        if self.communicate_calls == 1:
            raise subprocess.TimeoutExpired("worker", timeout)
        return "", ""

    def kill(self):
        self.killed = True


class EbayHardTimeoutIsolationTests(unittest.TestCase):
    def setUp(self):
        self.original_scraper = watcher.scrape_ebay_sold
        self.installed = isolation._INSTALLED
        self.original_delegate = isolation._ORIGINAL_SCRAPE_EBAY_SOLD

    def tearDown(self):
        watcher.scrape_ebay_sold = self.original_scraper
        isolation._INSTALLED = self.installed
        isolation._ORIGINAL_SCRAPE_EBAY_SOLD = self.original_delegate

    def _lot(self):
        return watcher.Lot(
            url="https://gradedcardcenter.com/item/public",
            title="PSA 10 Pikachu",
            current_price=50.0,
            source_type="fixed",
            grader="PSA",
            grade="10",
            card_set="151",
            card_number="#025/165",
            language="English",
        )

    def test_worker_env_scrubs_credentials_but_keeps_ebay_runtime(self):
        env = {
            "PATH": "/usr/bin",
            "GITHUB_TOKEN": "secret",
            "GCC_SESSION_B64": "secret",
            "POKETRACE_API_KEY": "secret",
            "NTFY_TOPIC": "secret",
            "EBAY_NAV_TIMEOUT": "10000",
            "EBAY_PAGE_WAIT_MS": "700",
        }
        with patch.dict(isolation.os.environ, env, clear=True):
            child = isolation._worker_env()

        self.assertEqual(child["PATH"], "/usr/bin")
        self.assertEqual(child["EBAY_NAV_TIMEOUT"], "10000")
        self.assertEqual(child["EBAY_PAGE_WAIT_MS"], "700")
        self.assertEqual(child["V4_EBAY_ISOLATED_WORKER"], "1")
        self.assertNotIn("GITHUB_TOKEN", child)
        self.assertNotIn("GCC_SESSION_B64", child)
        self.assertNotIn("POKETRACE_API_KEY", child)
        self.assertNotIn("NTFY_TOPIC", child)

    def test_decode_result_preserves_exact_comparable_fields(self):
        raw = json.dumps(
            {
                "status": watcher.EXTERNAL_MATCHED,
                "note": "exact",
                "sales": [
                    {
                        "price": 123.45,
                        "source": "ebay",
                        "grader": "PSA",
                        "grade": 10,
                        "sold_at": "2026-08-20T12:00:00+00:00",
                        "context": "sold",
                        "exact_card": True,
                        "match_score": 100,
                        "grade_qualifier": None,
                        "proven_commercial_dimensions": ["finish"],
                        "identity_provenance": "exact",
                    }
                ],
            }
        )

        result = isolation._decode_result(raw)

        self.assertEqual(result.status, watcher.EXTERNAL_MATCHED)
        self.assertEqual(len(result.sales), 1)
        self.assertEqual(result.sales[0].price, 123.45)
        self.assertEqual(result.sales[0].proven_commercial_dimensions, ("finish",))
        self.assertEqual(result.sales[0].sold_at.year, 2026)

    def test_hung_worker_is_killed_and_returns_provider_error_not_clean_no_match(self):
        proc = _HungProcess()
        with (
            patch.object(isolation.subprocess, "Popen", return_value=proc),
            patch.object(isolation, "_hard_timeout_seconds", return_value=12),
            patch.object(isolation.os, "getpgid", return_value=4321),
            patch.object(isolation.os, "killpg") as killpg,
            patch.object(watcher, "log") as log,
        ):
            result = isolation._run_isolated_ebay(self._lot())

        killpg.assert_called_once_with(4321, isolation.signal.SIGKILL)
        self.assertEqual(result.status, watcher.EXTERNAL_PROVIDER_ERROR)
        self.assertEqual(result.sales, [])
        self.assertIn("hard timeout", result.note.lower())
        self.assertTrue(any("HARD TIMEOUT" in call.args[0] for call in log.call_args_list))

    def test_successful_worker_result_is_returned_without_touching_parent_page(self):
        payload = json.dumps(
            {"status": watcher.EXTERNAL_CLEAN_NO_MATCH, "note": "none", "sales": []}
        )
        proc = _SuccessfulProcess(payload)
        poisoned_parent_page = Mock()
        poisoned_parent_page.goto.side_effect = AssertionError("parent page must not be used")
        with patch.object(isolation.subprocess, "Popen", return_value=proc):
            result = isolation._isolated_scrape_ebay_sold(
                poisoned_parent_page, self._lot(), with_status=True
            )

        self.assertEqual(result.status, watcher.EXTERNAL_CLEAN_NO_MATCH)
        poisoned_parent_page.goto.assert_not_called()

    def test_worker_failure_is_provider_error(self):
        proc = _SuccessfulProcess("")
        proc.returncode = 2
        with (
            patch.object(isolation.subprocess, "Popen", return_value=proc),
            patch.object(watcher, "log"),
        ):
            result = isolation._run_isolated_ebay(self._lot())

        self.assertEqual(result.status, watcher.EXTERNAL_PROVIDER_ERROR)
        self.assertEqual(result.sales, [])

    def test_installer_replaces_only_ebay_scraper(self):
        ebay = Mock()
        psa = watcher.scrape_psa_apr
        watcher.scrape_ebay_sold = ebay
        isolation._INSTALLED = False
        isolation._ORIGINAL_SCRAPE_EBAY_SOLD = None

        isolation.install_v4_ebay_hard_timeout_isolation()

        self.assertIs(isolation._ORIGINAL_SCRAPE_EBAY_SOLD, ebay)
        self.assertIs(watcher.scrape_ebay_sold, isolation._isolated_scrape_ebay_sold)
        self.assertIs(watcher.scrape_psa_apr, psa)


if __name__ == "__main__":
    unittest.main()
