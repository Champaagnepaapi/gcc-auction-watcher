"""Reduce Playwright IPC while preserving the existing V4 eBay scraper semantics.

The canonical scraper still owns query construction, SOLD filters, identity matching,
price parsing and provider status. This module only caches the visible text of
`li.s-item` nodes in one bulk Playwright call inside the isolated eBay worker.
If bulk extraction is unavailable or fails, the original per-item `inner_text`
path is used unchanged.
"""
from __future__ import annotations


_EBAY_ITEM_SELECTOR = "li.s-item"


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


class EbayBulkTextPageProxy:
    """Page proxy that changes only the eBay result-card locator."""

    def __init__(self, page):
        self._page = page

    def __getattr__(self, name):
        return getattr(self._page, name)

    def locator(self, selector, *args, **kwargs):
        locator = self._page.locator(selector, *args, **kwargs)
        if selector == _EBAY_ITEM_SELECTOR:
            return BulkTextItemLocator(locator)
        return locator
