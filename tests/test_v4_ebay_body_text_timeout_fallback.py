import unittest
from contextlib import contextmanager

import v4_ebay_stage_timing as timing


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


class _Locator:
    def __init__(self, *, inner_value="body", inner_error=None, text_value="body", text_error=None):
        self.inner_value = inner_value
        self.inner_error = inner_error
        self.text_value = text_value
        self.text_error = text_error
        self.inner_calls = 0
        self.text_calls = []

    def inner_text(self, *args, **kwargs):
        self.inner_calls += 1
        if self.inner_error is not None:
            raise self.inner_error
        return self.inner_value

    def text_content(self, *args, **kwargs):
        self.text_calls.append((args, kwargs))
        if self.text_error is not None:
            raise self.text_error
        return self.text_value

    def count(self):
        return 0

    def all_inner_texts(self):
        return []

    def nth(self, index):
        return self


class _Page:
    def __init__(self, body, items=None):
        self.body = body
        self.items = items or _Locator()
        self.goto_calls = 0

    def locator(self, selector, *args, **kwargs):
        if selector == "body":
            return self.body
        if selector == timing._EBAY_ITEM_SELECTOR:
            return self.items
        return _Locator()

    def goto(self, *args, **kwargs):
        self.goto_calls += 1
        return "ok"

    def wait_for_timeout(self, *args, **kwargs):
        return None

    def content(self, *args, **kwargs):
        return "<html></html>"


class EbayBodyTextTimeoutFallbackTests(unittest.TestCase):
    def test_body_inner_text_timeout_uses_one_bounded_same_dom_text_content_read(self):
        body = _Locator(
            inner_error=TimeoutError("visible text timed out"),
            text_value="Pardon our interruption",
        )
        recorder = _Recorder()
        raw_page = _Page(body)
        page = timing.EbayStageTimingPageProxy(raw_page, recorder)

        value = page.locator("body").inner_text(timeout=2500)

        self.assertEqual(value, "Pardon our interruption")
        self.assertEqual(body.inner_calls, 1)
        self.assertEqual(
            body.text_calls,
            [((), {"timeout": timing._BODY_TEXT_FALLBACK_TIMEOUT_MS})],
        )
        self.assertEqual(raw_page.goto_calls, 0)
        self.assertEqual(
            recorder.events,
            [
                "body_inner_text_start",
                "body_inner_text_error",
                "body_text_content_start",
                "body_text_content_done",
            ],
        )

    def test_non_timeout_body_error_is_never_swallowed(self):
        body = _Locator(inner_error=RuntimeError("boom"))
        page = timing.EbayStageTimingPageProxy(_Page(body), _Recorder())

        with self.assertRaises(RuntimeError):
            page.locator("body").inner_text(timeout=2500)

        self.assertEqual(body.inner_calls, 1)
        self.assertEqual(body.text_calls, [])

    def test_fallback_failure_remains_fail_closed(self):
        body = _Locator(
            inner_error=TimeoutError("visible text timed out"),
            text_error=TimeoutError("same DOM fallback timed out"),
        )
        recorder = _Recorder()
        page = timing.EbayStageTimingPageProxy(_Page(body), recorder)

        with self.assertRaises(TimeoutError):
            page.locator("body").inner_text(timeout=2500)

        self.assertEqual(len(body.text_calls), 1)
        self.assertEqual(
            recorder.events,
            [
                "body_inner_text_start",
                "body_inner_text_error",
                "body_text_content_start",
                "body_text_content_error",
            ],
        )

    def test_item_text_timeout_does_not_use_body_fallback(self):
        items = _Locator(inner_error=TimeoutError("item timed out"))
        page = timing.EbayStageTimingPageProxy(_Page(_Locator(), items), _Recorder())

        with self.assertRaises(TimeoutError):
            page.locator(timing._EBAY_ITEM_SELECTOR).inner_text(timeout=2500)

        self.assertEqual(items.text_calls, [])

    def test_fallback_remains_active_when_timing_output_is_disabled(self):
        body = _Locator(inner_error=TimeoutError("visible text timed out"), text_value="body")
        telemetry = timing.EbayStageTelemetry(enabled=False)
        page = timing.EbayStageTimingPageProxy(_Page(body), telemetry)

        self.assertEqual(page.locator("body").inner_text(timeout=2500), "body")
        self.assertEqual(len(body.text_calls), 1)


if __name__ == "__main__":
    unittest.main()
