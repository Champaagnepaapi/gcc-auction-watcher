"""Reduce Playwright IPC while preserving the existing V4 eBay scraper semantics.

The canonical scraper still owns query construction, SOLD filters, identity matching,
price parsing and provider status. This module caches the visible text of
`li.s-item` nodes in one bulk Playwright call inside the isolated eBay worker.
If bulk extraction is unavailable or fails, the original per-item `inner_text`
path is used unchanged.

When the canonical body visible-text read has already exhausted the existing #251
same-DOM fallback and still raises `TimeoutError`, this proxy may reuse the same
structured `li.s-item` surface once as a body-classification fallback. Recovery is
allowed only when readable result-row text contains an EUR price marker; otherwise
the original timeout is re-raised fail-closed. No navigation, reload, wait or
second provider request is performed.
"""
from __future__ import annotations

import re


_EBAY_ITEM_SELECTOR = "li.s-item"
_EBAY_BODY_SELECTOR = "body"
_EBAY_PRICE_MARKER_RE = re.compile(r"(?:€|\bEUR\b)", re.I)


class _CachedItem:
    def __init__(self, owner: "BulkTextItemLocator", delegate, index: int):
        self._owner = owner
        self._delegate = delegate
        self._index = index

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def inner_text(self, *args, **kwargs):
        texts = self._owner._bulk_texts()
        if texts is not None and 0 <= self._index < len(texts):
            return texts[self._index]
        return self._delegate.inner_text(*args, **kwargs)


class BulkTextItemLocator:
    """Locator proxy that bulk-loads item text once, then serves indexed reads."""

    def __init__(self, delegate):
        self._delegate = delegate
        self._bulk_attempted = False
        self._texts: list[str] | None = None

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def _bulk_texts(self) -> list[str] | None:
        if self._bulk_attempted:
            return self._texts
        self._bulk_attempted = True
        try:
            values = self._delegate.all_inner_texts()
        except Exception:
            return None
        if not isinstance(values, list):
            return None
        self._texts = ["" if value is None else str(value) for value in values]
        return self._texts

    def nth(self, index: int):
        return _CachedItem(self, self._delegate.nth(index), int(index))


class _BodyTextLocator:
    """Reuse readable structured result text only after the body path times out."""

    def __init__(self, owner: "EbayBulkTextPageProxy", delegate):
        self._owner = owner
        self._delegate = delegate

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def inner_text(self, *args, **kwargs):
        try:
            return self._delegate.inner_text(*args, **kwargs)
        except Exception as exc:
            if exc.__class__.__name__ != "TimeoutError":
                raise
            fallback = self._owner._structured_item_body_fallback()
            if fallback is None:
                raise
            return fallback


class EbayBulkTextPageProxy:
    """Page proxy for eBay result-card text and conservative body-timeout salvage."""

    def __init__(self, page):
        self._page = page

    def __getattr__(self, name):
        return getattr(self._page, name)

    def _structured_item_body_fallback(self) -> str | None:
        """Return already-loaded result text only when provider rows are credible.

        Requiring at least one EUR price marker prevents an unreadable/challenge
        surface from becoming a clean no-match merely because some `li.s-item`
        node exists. Any extraction error or weak/empty surface remains fail-closed.
        """
        try:
            values = self._page.locator(_EBAY_ITEM_SELECTOR).all_inner_texts()
        except Exception:
            return None
        if not isinstance(values, list):
            return None
        texts = [
            str(value).strip()
            for value in values
            if value is not None and str(value).strip()
        ]
        if not texts:
            return None
        if not any(_EBAY_PRICE_MARKER_RE.search(text) for text in texts):
            return None
        return "\n".join(texts)

    def locator(self, selector, *args, **kwargs):
        locator = self._page.locator(selector, *args, **kwargs)
        if selector == _EBAY_ITEM_SELECTOR:
            return BulkTextItemLocator(locator)
        if selector == _EBAY_BODY_SELECTOR:
            return _BodyTextLocator(self, locator)
        return locator
