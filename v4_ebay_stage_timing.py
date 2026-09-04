"""Safe stage timing and bounded same-DOM text fallback for the V4 eBay worker.

Only technical stage names and monotonic elapsed milliseconds are emitted. No
query, card identity, URL, provider payload, credential or market value is ever
included in these markers. The parent process parses only the strict marker
format and discards all other child stderr.

The canonical eBay scraper reads the page body only to classify provider/challenge
state before parsing structured result rows. If that visible-text read alone times
out, the worker makes one bounded ``text_content`` read from the same already-loaded
DOM. This performs no navigation and no network retry; every other exception and
all structured SOLD/identity semantics remain unchanged.
"""
from __future__ import annotations

import os
import re
import sys
import time
from contextlib import contextmanager


_STAGE_PREFIX = "EBAY_STAGE|"
_STAGE_NAME_RE = re.compile(r"^[a-z0-9_]{1,48}$")
_EBAY_ITEM_SELECTOR = "li.s-item"
_BODY_TEXT_FALLBACK_TIMEOUT_MS = 700


def stage_timing_enabled() -> bool:
    return os.getenv("V4_EBAY_STAGE_TIMING_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


class EbayStageTelemetry:
    def __init__(self, *, enabled: bool | None = None):
        self.enabled = stage_timing_enabled() if enabled is None else bool(enabled)
        self._started = time.monotonic()

    def mark(self, name: str) -> None:
        if not self.enabled:
            return
        if not _STAGE_NAME_RE.fullmatch(name):
            raise ValueError("invalid eBay stage name")
        elapsed_ms = max(0, int(round((time.monotonic() - self._started) * 1000)))
        sys.stderr.write(f"{_STAGE_PREFIX}{name}|{elapsed_ms}\n")
        sys.stderr.flush()

    @contextmanager
    def span(self, name: str):
        self.mark(f"{name}_start")
        try:
            yield
        except BaseException:
            self.mark(f"{name}_error")
            raise
        else:
            self.mark(f"{name}_done")


class _TimedItem:
    def __init__(self, delegate, telemetry: EbayStageTelemetry, stage: str):
        self._delegate = delegate
        self._telemetry = telemetry
        self._stage = stage

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def inner_text(self, *args, **kwargs):
        with self._telemetry.span(self._stage):
            return self._delegate.inner_text(*args, **kwargs)


class _TimedLocator:
    def __init__(self, delegate, telemetry: EbayStageTelemetry, kind: str):
        self._delegate = delegate
        self._telemetry = telemetry
        self._kind = kind

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def count(self, *args, **kwargs):
        with self._telemetry.span(f"{self._kind}_count"):
            return self._delegate.count(*args, **kwargs)

    def all_inner_texts(self, *args, **kwargs):
        with self._telemetry.span(f"{self._kind}_bulk_text"):
            return self._delegate.all_inner_texts(*args, **kwargs)

    def text_content(self, *args, **kwargs):
        with self._telemetry.span(f"{self._kind}_text_content"):
            return self._delegate.text_content(*args, **kwargs)

    def inner_text(self, *args, **kwargs):
        try:
            with self._telemetry.span(f"{self._kind}_inner_text"):
                return self._delegate.inner_text(*args, **kwargs)
        except Exception as exc:
            if self._kind != "body" or exc.__class__.__name__ != "TimeoutError":
                raise

        # Production evidence run 33858699452 showed successful navigation
        # followed by repeated body.inner_text timeouts at the 2500 ms ceiling.
        # Read the same current DOM once with a shorter bound; do not navigate,
        # wait, reload or otherwise create a second provider request.
        value = self.text_content(timeout=_BODY_TEXT_FALLBACK_TIMEOUT_MS)
        return "" if value is None else str(value)

    def nth(self, index):
        return _TimedItem(
            self._delegate.nth(index),
            self._telemetry,
            f"{self._kind}_item_text",
        )


class EbayStageTimingPageProxy:
    """Instrument eBay worker stages and recover only the proven body-read timeout."""

    def __init__(self, page, telemetry: EbayStageTelemetry):
        self._page = page
        self._telemetry = telemetry

    def __getattr__(self, name):
        return getattr(self._page, name)

    def goto(self, *args, **kwargs):
        with self._telemetry.span("navigation"):
            return self._page.goto(*args, **kwargs)

    def wait_for_timeout(self, *args, **kwargs):
        with self._telemetry.span("page_wait"):
            return self._page.wait_for_timeout(*args, **kwargs)

    def content(self, *args, **kwargs):
        with self._telemetry.span("page_content"):
            return self._page.content(*args, **kwargs)

    def locator(self, selector, *args, **kwargs):
        delegate = self._page.locator(selector, *args, **kwargs)
        if selector == _EBAY_ITEM_SELECTOR:
            kind = "items"
        elif selector == "body":
            kind = "body"
        else:
            kind = "other"
        return _TimedLocator(delegate, self._telemetry, kind)
