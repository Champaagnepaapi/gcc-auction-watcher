"""Smart ordering for V4 external-market budget.

This module changes *only* which fixed-card identities receive scarce external
provider calls first.  It never changes discovery, fair value, max buy, matching,
or notification thresholds.  Auctions keep the canonical ending-soon ordering.
"""

from __future__ import annotations

from typing import Any

import watcher


_ORIGINAL_PREPARE = None
_ORIGINAL_EXTERNAL_SORT = None
_PRICE_DROP_BY_ITEM: dict[str, float] = {}


def _price_drop_pct(previous: Any, current: Any) -> float:
    try:
        old = float(previous)
        new = float(current)
    except (TypeError, ValueError):
        return 0.0
    if old <= 0 or new < 0 or new >= old:
        return 0.0
    return max(0.0, min(100.0, (old - new) / old * 100.0))


def _snapshot_previous_prices(state: dict) -> dict[str, float]:
    queue = state.get(watcher.FIXED_QUEUE_STATE_KEY)
    items = queue.get("items") if isinstance(queue, dict) else None
    if not isinstance(items, dict):
        return {}
    result: dict[str, float] = {}
    for item_id, record in items.items():
        if not isinstance(record, dict):
            continue
        try:
            price = float(record.get("last_price"))
        except (TypeError, ValueError):
            continue
        if price > 0:
            result[str(item_id)] = price
    return result


def _prepare_with_price_drop_memory(
    candidates,
    state,
    run_now,
    run_diagnostics,
    valuation_cap,
):
    previous = _snapshot_previous_prices(state)
    result = _ORIGINAL_PREPARE(
        candidates,
        state,
        run_now,
        run_diagnostics,
        valuation_cap,
    )
    selected, _category_by_id, _records = result
    _PRICE_DROP_BY_ITEM.clear()
    for lot in selected:
        item_id = watcher.fixed_listing_id(lot)
        drop = _price_drop_pct(previous.get(item_id), lot.current_price)
        if drop > 0:
            _PRICE_DROP_BY_ITEM[item_id] = drop
    return result


def external_priority_score(candidate) -> float:
    """Deterministic information-value score for fixed external calls."""
    lot = candidate.lot
    if lot.source_type == "auction":
        return 0.0

    score = 0.0
    item_id = watcher.fixed_listing_id(lot)
    drop = _PRICE_DROP_BY_ITEM.get(item_id, 0.0)
    score += min(100.0, drop * 2.0)

    diagnostics = getattr(candidate.gcc, "diagnostics", None)
    exact = getattr(diagnostics, "exact_grade_count", None)
    if exact is not None:
        if exact <= 0:
            score += 40.0
        elif exact == 1:
            score += 25.0
        elif exact == 2:
            score += 10.0

    grader = (lot.grader or "").strip().upper()
    if grader and grader != "PSA":
        score += 20.0

    try:
        price = float(lot.current_price)
    except (TypeError, ValueError):
        price = watcher.MAX_PRICE
    if price >= 0:
        score += max(0.0, min(20.0, (watcher.MAX_PRICE - price) / 5.0))

    if getattr(candidate.gcc, "branch", "") != watcher.GCC_BRANCH_SUPPORTED:
        score += 15.0

    return round(score, 4)


def _smart_external_queue_sort_key(candidate, cache_status: str) -> tuple:
    original = _ORIGINAL_EXTERNAL_SORT(candidate, cache_status)
    if candidate.lot.source_type == "auction":
        # Critical invariant: auction ordering remains exactly the canonical
        # ending-soon ordering.  No fixed-card heuristic can jump an auction.
        return original
    category_rank = original[0] if original else 999
    cache_rank = original[1] if len(original) > 1 else 999
    tail = original[2:] if len(original) > 2 else (candidate.lot.url,)
    return (category_rank, -external_priority_score(candidate), cache_rank, *tail)


def install_v4_smart_external_priority() -> None:
    global _ORIGINAL_PREPARE, _ORIGINAL_EXTERNAL_SORT
    if getattr(watcher, "_v4_smart_external_priority_installed", False):
        return
    _ORIGINAL_PREPARE = watcher._prepare_fixed_economic_queue
    _ORIGINAL_EXTERNAL_SORT = watcher._external_queue_sort_key
    watcher._prepare_fixed_economic_queue = _prepare_with_price_drop_memory
    watcher._external_queue_sort_key = _smart_external_queue_sort_key
    watcher._v4_smart_external_priority_installed = True
    watcher.log(
        "External priority: smart fixed ordering enabled "
        "(price-drop/sparse-history/secondary-grader/low-price; auctions unchanged)"
    )
