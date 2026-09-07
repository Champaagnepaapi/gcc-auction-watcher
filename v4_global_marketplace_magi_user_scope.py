"""Exact user-scope exclusions and active-only retrieval for Magi opportunities.

Magi's public search form exposes ``forms_search_items[status]=presented`` for
items currently presented for sale. The Global opportunity lane therefore asks
for that provider-native status instead of retrieving SOLD rows only to reject
them later. Explicit detail-page SOLD guards remain in place as defense in depth.

This is intentionally not a generic Trainer/supporter filter. Only the reviewed
subjects the operator has explicitly excluded are removed from the broad Magi
candidate stream. Filtering happens before detail-page/TCGdex work, so these
rows cannot consume identity budget.
"""
from __future__ import annotations

import unicodedata

import v4_global_marketplace_scan as scan


_EXCLUDED_MARKERS = (
    "ポケモンだいすきクラブ",
    "ポケモンパルシティ",
    "バトルロードサマー",
)
_PRESENTED_STATUS_PARAMETER = "forms_search_items%5Bstatus%5D=presented"
_ORIGINAL_BROAD_ROWS = None
_INSTALLED = False


def _compact(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).replace(" ", "")


def excluded_magi_opportunity_subject(value: object) -> bool:
    text = _compact(value)
    return any(marker in text for marker in _EXCLUDED_MARKERS)


def _presented_only_url(url: object) -> str:
    raw = str(url or "")
    if "magi.camp/items/search" not in raw or _PRESENTED_STATUS_PARAMETER in raw:
        return raw
    separator = "&" if "?" in raw else "?"
    return f"{raw}{separator}{_PRESENTED_STATUS_PARAMETER}"


class _PresentedOnlyPage:
    """Proxy only the Magi search navigation; delegate every other page API."""

    def __init__(self, page):
        self._page = page

    def goto(self, url, *args, **kwargs):
        return self._page.goto(_presented_only_url(url), *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._page, name)


def _in_scope_broad_rows(page):
    assert _ORIGINAL_BROAD_ROWS is not None
    # Provider-native `presented` status removes historical SOLD rows at source.
    # The downstream detail availability check is intentionally retained.
    rows = _ORIGINAL_BROAD_ROWS(_PresentedOnlyPage(page))
    output = []
    for ask in rows:
        evidence = "\n".join(
            str(value or "")
            for value in (getattr(ask, "title", ""), getattr(ask, "text", ""))
            if value
        )
        if excluded_magi_opportunity_subject(evidence):
            continue
        output.append(ask)
    return output


def install_global_marketplace_magi_user_scope() -> None:
    global _ORIGINAL_BROAD_ROWS, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_BROAD_ROWS = scan._magi_broad_rows
    scan._magi_broad_rows = _in_scope_broad_rows
    _INSTALLED = True