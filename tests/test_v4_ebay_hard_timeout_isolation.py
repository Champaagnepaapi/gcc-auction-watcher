import json
import subprocess
import unittest
from unittest.mock import Mock, patch

import v4_ebay_hard_timeout_isolation as isolation
import watcher


class _FakeStdin:
    def __init__(self):
        self.value = ""
        self.closed = False

    def write(self, value):
        self.value += value
        return len(value)

    def close(self):
        self.closed = True


class _Process:
    def __init__(self, *, cleanup_hangs=False, returncode=0):
        self.pid = 1234
        self.returncode = returncode
        self.stdin = _FakeStdin()
        self.cleanup_hangs = cleanup_hangs
        self.wait_calls = 0
        self.killed = False

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.cleanup_hangs and self.wait_calls == 1:
            raise subprocess.TimeoutExpired("worker", timeout)
        return self.returncode

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

    def _payload(self, *, status=None, note="none", sales=None):
        return json.dumps(
            {
                "status": status or watcher.EXTERNAL_CLEAN_NO_MATCH,
                "note": note,
                "sales": sales or [],
            }
        )

    def test_worker_env_scrubs_credentials_but_keeps_runtime_and_result_fd(self):
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
            child = isolation._worker_env(result_fd=17)

        self.assertEqual(child["PATH"], "/usr/bin")
        self.assertEqual(child["EBAY_NAV_TIMEOUT"], "10000")
        self.assertEqual(child["EBAY_PAGE_WAIT_MS"], "700")
        self.assertEqual(child["V4_EBAY_ISOLATED_WORKER"], "1")
        self.assertEqual(child["V4_EBAY_RESULT_FD"], "17")
        self.assertNotIn("GITHUB_TOKEN", child)
        self.assertNotIn("GCC_SESSION_B64", child)
        self.assertNotIn("POKETRACE_API_KEY", child)
        self.assertNotIn("NTFY_TOPIC", child)

    def test_cleanup_grace_is_tightly_bounded(self):
        with patch.dict(
            isolation.os.environ, {"V4_EBAY_CLEANUP_GRACE_SECONDS": "99"}, clear=True
        ):
            self.assertEqual(isolation._cleanup_grace_seconds(), 5.0)
        with patch.dict(
            isolation.os.environ, {"V4_EBAY_CLEANUP_GRACE_SECONDS": "0"}, clear=True
        ):
            self.assertEqual(isolation._cleanup_grace_seconds(), 0.25)

    def test_decode_result_preserves_exact_comparable_fields(self):
        raw = self._payload(
            status=watcher.EXTERNAL_MATCHED,
            note="exact",
            sales=[
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
        )

        result = isolation._decode_result(raw)

        self.assertEqual(result.status, watcher.EXTERNAL_MATCHED)
        self.assertEqual(len(result.sales), 1)
        self.assertEqual(result.sales[0].price, 123.45)
        self.assertEqual(result.sales[0].proven_commercial_dimensions, ("finish",))
        self.assertEqual(result.sales[0].sold_at.year, 2026)

    def test_no_result_before_deadline_is_killed_and_provider_error(self):
        proc = _Process()
        with (
            patch.object(isolation.subprocess, "Popen", return_value=proc),
            patch.object(isolation, "_read_early_result", side_effect=TimeoutError),
            patch.object(isolation, "_hard_timeout_seconds", return_value=12),
            patch.object(isolation.os, "killpg") as killpg,
            patch.object(watcher, "log") as log,
        ):
            result = isolation._run_isolated_ebay(self._lot())

        killpg.assert_called_once_with(proc.pid, isolation.signal.SIGKILL)
        self.assertEqual(result.status, watcher.EXTERNAL_PROVIDER_ERROR)
        self.assertEqual(result.sales, [])
        self.assertIn("hard timeout", result.note.lower())
        self.assertTrue(any("HARD TIMEOUT" in call.args[0] for call in log.call_args_list))

    def test_valid_result_is_returned_without_touching_parent_page(self):
        proc = _Process()
        poisoned_parent_page = Mock()
        poisoned_parent_page.goto.side_effect = AssertionError("parent page must not be used")
        with (
            patch.object(isolation.subprocess, "Popen", return_value=proc),
            patch.object(isolation, "_read_early_result", return_value=self._payload()),
        ):
            result = isolation._isolated_scrape_ebay_sold(
                poisoned_parent_page, self._lot(), with_status=True
            )

        self.assertEqual(result.status, watcher.EXTERNAL_CLEAN_NO_MATCH)
        poisoned_parent_page.goto.assert_not_called()
        self.assertTrue(proc.stdin.closed)
        self.assertIn("Pikachu", proc.stdin.value)

    def test_valid_result_survives_browser_cleanup_hang_and_group_is_killed(self):
        proc = _Process(cleanup_hangs=True)
        raw = self._payload(
            status=watcher.EXTERNAL_MATCHED,
            note="exact sold",
            sales=[
                {
                    "price": 88.0,
                    "source": "ebay",
                    "grader": "PSA",
                    "grade": 10,
                    "sold_at": "2026-09-01T12:00:00+00:00",
                    "context": "sold",
                    "exact_card": True,
                    "match_score": 100,
                    "grade_qualifier": None,
                    "proven_commercial_dimensions": ["finish"],
                    "identity_provenance": "exact",
                }
            ],
        )
        with (
            patch.object(isolation.subprocess, "Popen", return_value=proc),
            patch.object(isolation, "_read_early_result", return_value=raw),
            patch.object(isolation, "_cleanup_grace_seconds", return_value=2.0),
            patch.object(isolation.os, "killpg") as killpg,
            patch.object(watcher, "log") as log,
        ):
            result = isolation._run_isolated_ebay(self._lot())

        killpg.assert_called_once_with(proc.pid, isolation.signal.SIGKILL)
        self.assertEqual(result.status, watcher.EXTERNAL_MATCHED)
        self.assertEqual(len(result.sales), 1)
        self.assertEqual(result.sales[0].price, 88.0)
        message = "\n".join(call.args[0] for call in log.call_args_list)
        self.assertIn("valid result preserved", message)
        self.assertNotIn("HARD TIMEOUT", message)

    def test_invalid_early_result_remains_fail_closed(self):
        proc = _Process()
        with (
            patch.object(isolation.subprocess, "Popen", return_value=proc),
            patch.object(isolation, "_read_early_result", return_value="not-json"),
            patch.object(isolation.os, "killpg") as killpg,
            patch.object(watcher, "log"),
        ):
            result = isolation._run_isolated_ebay(self._lot())

        killpg.assert_called_once_with(proc.pid, isolation.signal.SIGKILL)
        self.assertEqual(result.status, watcher.EXTERNAL_PROVIDER_ERROR)
        self.assertEqual(result.sales, [])

    def test_worker_closing_result_pipe_before_payload_is_provider_error(self):
        proc = _Process(returncode=2)
        with (
            patch.object(isolation.subprocess, "Popen", return_value=proc),
            patch.object(isolation, "_read_early_result", side_effect=EOFError),
            patch.object(isolation.os, "killpg"),
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
