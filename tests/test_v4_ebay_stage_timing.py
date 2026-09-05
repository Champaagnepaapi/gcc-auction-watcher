import inspect
import io
import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import v4_ebay_hard_timeout_isolation as isolation
import v4_ebay_isolated_worker as worker
import v4_ebay_stage_timing as timing
import watcher
from v4_ebay_bulk_result_text import EbayBulkTextPageProxy


class _Recorder:
    def __init__(self):
        self.events = []

    @contextmanager
    def span(self, name):
        self.events.append(f"{name}_start")
        try:
            yield
        except BaseException:
            self.events.append(f"{name}_error")
            raise
        else:
            self.events.append(f"{name}_done")


class _Item:
    def __init__(self, text):
        self.text = text
        self.inner_text_calls = 0

    def inner_text(self, *args, **kwargs):
        self.inner_text_calls += 1
        return self.text


class _Items:
    def __init__(self, texts, *, bulk_error=False):
        self.items = [_Item(text) for text in texts]
        self.bulk_error = bulk_error
        self.bulk_calls = 0

    def count(self):
        return len(self.items)

    def all_inner_texts(self):
        self.bulk_calls += 1
        if self.bulk_error:
            raise RuntimeError("bulk unavailable")
        return [item.text for item in self.items]

    def nth(self, index):
        return self.items[index]


class _Body:
    def inner_text(self, *args, **kwargs):
        return "body"


class _Page:
    def __init__(self, items):
        self.items = items
        self.body = _Body()
        self.url = "https://www.ebay.fr/sch/i.html"

    def goto(self, *args, **kwargs):
        return "goto-result"

    def wait_for_timeout(self, *args, **kwargs):
        return None

    def content(self, *args, **kwargs):
        return "<html></html>"

    def locator(self, selector, *args, **kwargs):
        if selector == "li.s-item":
            return self.items
        if selector == "body":
            return self.body
        return self.body


class _FakeStdin:
    def write(self, value):
        return len(value)

    def close(self):
        return None


class _Process:
    def __init__(self):
        self.pid = 4321
        self.returncode = None
        self.stdin = _FakeStdin()

    def wait(self, timeout=None):
        self.returncode = -9
        return self.returncode

    def kill(self):
        self.returncode = -9


class EbayStageTimingTests(unittest.TestCase):
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

    def test_marker_contains_only_stage_name_and_elapsed_ms(self):
        stream = io.StringIO()
        with (
            patch.object(timing.time, "monotonic", side_effect=[100.0, 100.123]),
            patch.object(timing.sys, "stderr", stream),
        ):
            telemetry = timing.EbayStageTelemetry(enabled=True)
            telemetry.mark("worker_start")

        self.assertEqual(stream.getvalue(), "EBAY_STAGE|worker_start|123\n")

    def test_invalid_stage_name_is_rejected(self):
        telemetry = timing.EbayStageTelemetry(enabled=True)
        with self.assertRaises(ValueError):
            telemetry.mark("query=secret")

    def test_bulk_layer_preserves_semantics_and_times_bulk_rpc(self):
        items = _Items(["first", "second"])
        recorder = _Recorder()
        raw = _Page(items)
        timed = timing.EbayStageTimingPageProxy(raw, recorder)
        page = EbayBulkTextPageProxy(timed)

        self.assertEqual(page.goto("url"), "goto-result")
        cards = page.locator("li.s-item")
        self.assertEqual(cards.count(), 2)
        self.assertEqual(cards.nth(0).inner_text(), "first")
        self.assertEqual(cards.nth(1).inner_text(), "second")

        self.assertEqual(items.bulk_calls, 1)
        self.assertEqual([item.inner_text_calls for item in items.items], [0, 0])
        self.assertIn("navigation_start", recorder.events)
        self.assertIn("items_count_start", recorder.events)
        self.assertIn("items_bulk_text_start", recorder.events)
        self.assertNotIn("items_item_text_start", recorder.events)

    def test_bulk_failure_times_original_per_item_fallback(self):
        items = _Items(["first"], bulk_error=True)
        recorder = _Recorder()
        page = EbayBulkTextPageProxy(
            timing.EbayStageTimingPageProxy(_Page(items), recorder)
        )

        self.assertEqual(page.locator("li.s-item").nth(0).inner_text(), "first")

        self.assertIn("items_bulk_text_error", recorder.events)
        self.assertIn("items_item_text_start", recorder.events)
        self.assertIn("items_item_text_done", recorder.events)
        self.assertEqual(items.items[0].inner_text_calls, 1)

    def test_body_challenge_probe_is_timed_without_body_text_in_marker(self):
        recorder = _Recorder()
        timed = timing.EbayStageTimingPageProxy(_Page(_Items([])), recorder)

        self.assertEqual(timed.locator("body").inner_text(), "body")

        self.assertEqual(
            recorder.events,
            ["body_inner_text_start", "body_inner_text_done"],
        )

    def test_parent_summary_ignores_all_non_marker_child_stderr(self):
        stderr = "\n".join(
            [
                "query=SECRET CARD DATA",
                "EBAY_STAGE|worker_start|0",
                "EBAY_STAGE|scrape_start|100",
                "EBAY_STAGE|navigation_start|200",
                "EBAY_STAGE|navigation_done|1100",
                "provider payload SECRET",
                "EBAY_STAGE|scrape_done|1200",
                "EBAY_STAGE|worker_done|1300",
            ]
        )

        summary = isolation._stage_timing_summary(stderr)

        self.assertIn("elapsed=1300ms", summary)
        self.assertIn("worker=1300ms/1", summary)
        self.assertIn("scrape=1100ms/1", summary)
        self.assertIn("navigation=900ms/1", summary)
        self.assertIn("last=worker_done@1300ms", summary)
        self.assertNotIn("SECRET", summary)
        self.assertNotIn("query", summary)

    def test_parent_summary_surfaces_body_text_fallback_and_error_count(self):
        success_stderr = "\n".join(
            [
                "provider payload SECRET",
                "EBAY_STAGE|worker_start|0",
                "EBAY_STAGE|body_inner_text_start|100",
                "EBAY_STAGE|body_inner_text_error|2600",
                "EBAY_STAGE|body_text_content_start|2601",
                "EBAY_STAGE|body_text_content_done|2751",
                "EBAY_STAGE|worker_done|2800",
            ]
        )
        failure_stderr = "\n".join(
            [
                "EBAY_STAGE|worker_start|0",
                "EBAY_STAGE|body_inner_text_start|100",
                "EBAY_STAGE|body_inner_text_error|2600",
                "EBAY_STAGE|body_text_content_start|2601",
                "EBAY_STAGE|body_text_content_error|3301",
                "EBAY_STAGE|worker_done|3400",
            ]
        )

        success = isolation._stage_timing_summary(success_stderr)
        failure = isolation._stage_timing_summary(failure_stderr)

        self.assertIn("body_inner_text=2500ms/1", success)
        self.assertIn("body_text_content=150ms/1", success)
        self.assertIn("body_text_content_errors=0", success)
        self.assertIn("body_text_content=700ms/1", failure)
        self.assertIn("body_text_content_errors=1", failure)
        self.assertNotIn("SECRET", success)

    def test_hard_timeout_surfaces_last_safe_stage_only(self):
        stderr = "\n".join(
            [
                "private query SECRET",
                "EBAY_STAGE|worker_start|0",
                "EBAY_STAGE|scrape_start|300",
                "EBAY_STAGE|navigation_start|500",
            ]
        )
        proc = _Process()
        with (
            patch.object(isolation.subprocess, "Popen", return_value=proc),
            patch.object(isolation, "_read_early_result", side_effect=TimeoutError),
            patch.object(isolation, "_hard_timeout_seconds", return_value=12),
            patch.object(isolation, "_stderr_from_file", return_value=stderr),
            patch.object(isolation.os, "killpg"),
            patch.object(watcher, "log") as log,
        ):
            result = isolation._run_isolated_ebay(self._lot())

        self.assertEqual(result.status, watcher.EXTERNAL_PROVIDER_ERROR)
        message = "\n".join(call.args[0] for call in log.call_args_list)
        self.assertIn("HARD TIMEOUT", message)
        self.assertIn("last=navigation_start@500ms", message)
        self.assertNotIn("SECRET", message)
        self.assertNotIn("private query", message)

    def test_worker_result_pipe_is_complete_newline_delimited_utf8(self):
        read_fd, write_fd = os.pipe()
        try:
            with patch.dict(
                worker.os.environ,
                {worker._RESULT_FD_ENV: str(write_fd)},
                clear=True,
            ):
                emitted = worker._emit_early_result('{"note":"Pokémon"}')
            raw = os.read(read_fd, 4096)
        finally:
            try:
                os.close(read_fd)
            except OSError:
                pass
            try:
                os.close(write_fd)
            except OSError:
                pass

        self.assertTrue(emitted)
        self.assertEqual(raw.decode("utf-8"), '{"note":"Pokémon"}\n')

    def test_worker_emits_result_before_browser_close_in_main_protocol(self):
        source = inspect.getsource(worker.main)
        self.assertLess(source.index("_emit_early_result"), source.index("browser.close"))
        self.assertLess(source.index("context.close"), source.index("_emit_early_result"))

    def test_worker_env_keeps_public_timing_switches_but_scrubs_secrets(self):
        env = {
            "PATH": "/usr/bin",
            "V4_EBAY_STAGE_TIMING_ENABLED": "false",
            "V4_EBAY_STAGE_TIMING_LOG_SUCCESS": "false",
            "SOME_API_KEY": "secret",
        }
        with patch.dict(isolation.os.environ, env, clear=True):
            child = isolation._worker_env()

        self.assertEqual(child["V4_EBAY_STAGE_TIMING_ENABLED"], "false")
        self.assertEqual(child["V4_EBAY_STAGE_TIMING_LOG_SUCCESS"], "false")
        self.assertNotIn("SOME_API_KEY", child)


if __name__ == "__main__":
    unittest.main()
