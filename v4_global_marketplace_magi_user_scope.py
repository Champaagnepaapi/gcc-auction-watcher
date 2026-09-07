"""Exact user-scope exclusions for Magi opportunity discovery.

This is intentionally not a generic Trainer/supporter filter. Only the reviewed
subjects the operator has explicitly excluded are removed from the broad Magi
candidate stream. Filtering happens before detail-page/TCGdex work, so these
rows cannot consume identity budget.
"""
from __future__ import annotations

import unicodedata
from collections.abc import Sequence

import v4_global_marketplace_scan as scan


_EXCLUDED_MARKERS = (
    "ポケモンだいすきクラブ",
    "ポケモンパルシティ",
    "バトルロードサマー",
)
_ORIGINAL_BROAD_ROWS = None
_INSTALLED = False


def _compact(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).replace(" ", "")


def excluded_magi_opportunity_subject(value: object) -> bool:
    text = _compact(value)
    return any(marker in text for marker in _EXCLUDED_MARKERS)


def _in_scope_broad_rows(page):
    assert _ORIGINAL_BROAD_ROWS is not None
    rows = _ORIGINAL_BROAD_ROWS(page)
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
