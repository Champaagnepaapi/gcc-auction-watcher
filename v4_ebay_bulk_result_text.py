"""Reduce Playwright IPC while preserving the existing V4 eBay scraper semantics.

The canonical scraper still owns query construction, SOLD filters, identity matching,
price parsing and provider status. On the normal path this module caches the visible
text of `li.s-item` nodes in one bulk Playwright call inside the isolated eBay
worker. If normal bulk extraction is unavailable or fails, the original per-item
`inner_text` path is used unchanged.

When the canonical body visible-text read has already exhausted the existing #251
same-DOM fallback and still raises `TimeoutError`, this proxy may reuse a small,
bounded sample of the same structured `li.s-item` surface as a body-classification
fallback. Recovery is allowed only when readable result-row text contains an EUR
price marker; otherwise the original timeout is re-raised fail-closed. Once this
recovery path is active, the unbounded bulk primitive is disabled for the remaining
structured reads so the canonical scraper's existing per-item 600 ms timeout stays
in control. No navigation, reload, wait or second provider request is performed.
"""
from __future__ import annotations

import re


_EBAY_ITEM_SELECTOR = "li.s-item"
_EBAY_BODY_SELECTOR = "body"
_EBAY_PRICE_MARKER_RE = re.compile(r"(?:€|\bEUR\b)", re.I)
_BODY_SALVAGE_MAX_ROWS = 4
_BODY_SALVAGE_ITEM_TIMEOUT_MS = 600


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

    def __init__(self, delegate, *, allow_bulk: bool = True):
        self._delegate = delegate
        self._allow_bulk = bool(allow_bulk)
        self._bulk_attempted = False
        self._texts: list[str] | None = None

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def _bulk_texts(self) -> list[str] | None:
        if self._bulk_attempted:
            return self._texts
        self._bulk_attempted = True
        if not self._allow_bulk:
            return None
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
        self._body_salvage_active = False

    def __getattr__(self, name):
        return getattr(self._page, name)

    def _structured_item_body_fallback(self) -> str | None:
        """Return bounded already-loaded result text only when rows are credible.

        Natural production runs after #253 proved that `all_inner_texts()` can hang
        indefinitely on exactly the DOMs where both body reads time out. Probe only
        four result rows with the same bounded per-item primitive already used by
        the canonical parser. Requiring an EUR price marker keeps weak/challenge
        surfaces fail-closed.
        """
        items = self._page.locator(_EBAY_ITEM_SELECTOR)
        texts: list[str] = []
        for index in range(_BODY_SALVAGE_MAX_ROWS):
            try:
                value = items.nth(index).inner_text(
                    timeout=_BODY_SALVAGE_ITEM_TIMEOUT_MS
                )
            except Exception:
                continue
            text = "" if value is None else str(value).strip()
            if text:
                texts.append(text)

        if not texts:
            return None
        if not any(_EBAY_PRICE_MARKER_RE.search(text) for text in texts):
            return None

        # The problematic DOM is now known to have required structured salvage.
        # Avoid re-entering the unbounded bulk primitive when canonical parsing
        # subsequently asks for `li.s-item`; its existing per-item timeout remains
        # authoritative and every failure stays fail-closed.
        self._body_salvage_active = True
        return "\n".join(texts)

    def locator(self, selector, *args, **kwargs):
        locator = self._page.locator(selector, *args, **kwargs)
        if selector == _EBAY_ITEM_SELECTOR:
            return BulkTextItemLocator(
                locator,
                allow_bulk=not self._body_salvage_active,
            )
        if selector == _EBAY_BODY_SELECTOR:
            return _BodyTextLocator(self, locator)
        return locator
