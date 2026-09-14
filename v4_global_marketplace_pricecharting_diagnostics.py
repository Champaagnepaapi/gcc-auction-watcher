"""Bounded read-only PriceCharting lookup diagnostics for PR validation.

The wrapper adds no network call and changes no matching/economic decision. It
only prints the exact input identity plus the already-returned lookup status,
product locator and note. Production schedules are inert unless explicitly
opted in; pull-request validation enables the probe automatically.
"""
from __future__ import annotations

import os
from typing import Optional

import watcher
import v4_pricecharting_valuation as pc


_MAX_DIAGNOSTICS = 80
_ORIGINAL_LOOKUP = None
_INSTALLED = False
_count = 0


def _enabled() -> bool:
    value = os.getenv("GLOBAL_PRICECHARTING_DIAGNOSTICS", "").strip().casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    return os.getenv("GITHUB_EVENT_NAME", "").strip().casefold() == "pull_request"


def _label(lot: watcher.Lot) -> str:
    identity = watcher.extract_card_identity(lot)
    name = str(identity.get("core") or lot.title or "").replace("\n", " ").strip()
    number = str(lot.card_number or identity.get("ref") or "").strip()
    set_name = str(lot.card_set or identity.get("series") or "").replace("\n", " ").strip()
    language = str(lot.language or identity.get("language") or "").strip()
    grader = str(lot.grader or "").strip()
    grade = str(lot.grade or "").strip()
    return (
        f"name={name[:180]} | set={set_name[:140]} | number={number[:80]} | "
        f"language={language[:40]} | grader={grader[:20]} | grade={grade[:20]}"
    )


def _lookup_with_diagnostics(self: pc.PriceChartingProvider, lot: watcher.Lot) -> pc.PriceChartingLookup:
    global _count
    assert _ORIGINAL_LOOKUP is not None
    result = _ORIGINAL_LOOKUP(self, lot)
    if _enabled() and _count < _MAX_DIAGNOSTICS:
        _count += 1
        print(
            "[PRICECHARTING_DIAG] "
            f"status={result.status or 'UNKNOWN'} "
            f"product={str(result.product_id or '')[:300]} "
            f"note={str(result.note or '').replace(chr(10), ' ')[:400]} | "
            f"{_label(lot)}"
        )
    return result


def install_global_marketplace_pricecharting_diagnostics() -> None:
    global _ORIGINAL_LOOKUP, _INSTALLED, _count
    if _INSTALLED:
        return
    _ORIGINAL_LOOKUP = pc.PriceChartingProvider.lookup
    pc.PriceChartingProvider.lookup = _lookup_with_diagnostics
    _count = 0
    _INSTALLED = True
