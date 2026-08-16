from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional

import watcher


# This module changes scheduling/backoff only. It never changes identity, fair value,
# max_recommended, discount thresholds, or notification economics.
DEFAULT_FIXED_EBAY_RESERVE = 4
DEFAULT_BUDGET_PENDING_COOLDOWN_MINUTES = 5

_ORIGINAL_FETCH_EXTERNAL = None
_ORIGINAL_RECORD_FIXED_EXTERNAL_STATUS = None
_ORIGINAL_PREPARE_FIXED_QUEUE = None
_INSTALLED = False


def _configured_fixed_ebay_reserve(total_cap: int) -> int:
    total = max(0, int(total_cap))
    raw = os.getenv("V4_EBAY_FIXED_RESERVE_CARDS_PER_RUN", "").strip()
    if raw:
        try:
            requested = int(raw)
        except ValueError:
            requested = DEFAULT_FIXED_EBAY_RESERVE
    else:
        requested = DEFAULT_FIXED_EBAY_RESERVE if total >= 8 else max(1, total // 2)
    return max(0, min(total, requested))


def _budget_pending_cooldown_minutes() -> int:
    raw = os.getenv(
        "V4_EXTERNAL_PENDING_BUDGET_COOLDOWN_MINUTES",
        str(DEFAULT_BUDGET_PENDING_COOLDOWN_MINUTES),
    ).strip()
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_BUDGET_PENDING_COOLDOWN_MINUTES
    return max(0, min(30, value))


def _effective_ebay_cap_for_candidate(
    candidate: watcher.ValuationCandidate,
    *,
    total_cap: int,
    fixed_reserve: int,
) -> int:
    """Keep a bounded part of the eBay SOLD budget available for fixed cards.

    Auctions remain first in the canonical external queue. They simply cannot
    consume the fixed reserve. Fixed NEW/CHANGED work may use the reserve before
    P4 because first-evaluation safety remains higher priority than backlog drain.
    """
    total = max(0, int(total_cap))
    reserve = max(0, min(total, int(fixed_reserve)))
    if candidate.lot.source_type == "auction":
        return max(0, total - reserve)
    return total


def _normalize_legacy_budget_pending_backoff(
    state: dict,
    run_now: datetime,
) -> int:
    """Make old exponential budget-only P4 rows eligible without touching fresh cooldowns/provider errors."""
    root = state.get(watcher.FIXED_QUEUE_STATE_KEY)
    items = root.get("items") if isinstance(root, dict) else None
    if not isinstance(items, dict):
        return 0

    changed = 0
    for record in items.values():
        if not isinstance(record, dict):
            continue
        if record.get("last_evaluation_status") != watcher.REJECTION_EXTERNAL_PENDING:
            continue
        retry_count = int(record.get("retry_count") or 0)
        # The legacy implementation incremented retry_count for every budget
        # pending event. The new semantics always write retry_count=0, so this is
        # a deterministic one-way migration marker that does not erase the new
        # short 5-minute cooldown on subsequent runs.
        if retry_count <= 0:
            continue
        record["retry_count"] = 0
        record["retry_after"] = run_now.isoformat()
        changed += 1
    return changed


def _prepare_fixed_queue_with_pending_migration(
    candidates,
    state,
    run_now,
    run_diagnostics,
    valuation_cap,
):
    migrated = _normalize_legacy_budget_pending_backoff(state, run_now)
    if migrated:
        watcher.log(
            "External coverage drain: normalized "
            f"{migrated} legacy budget-pending P4 backoff row(s)"
        )
    return _ORIGINAL_PREPARE_FIXED_QUEUE(
        candidates,
        state,
        run_now,
        run_diagnostics,
        valuation_cap,
    )


def _record_fixed_external_status_with_budget_semantics(
    state: dict,
    lot: watcher.Lot,
    status: str,
    run_now: Optional[datetime] = None,
    adaptive_ttl_hours: Optional[int] = None,
) -> None:
    _ORIGINAL_RECORD_FIXED_EXTERNAL_STATUS(
        state,
        lot,
        status,
        run_now=run_now,
        adaptive_ttl_hours=adaptive_ttl_hours,
    )
    if status != watcher.REJECTION_EXTERNAL_PENDING or run_now is None:
        return

    root = state.get(watcher.FIXED_QUEUE_STATE_KEY)
    items = root.get("items") if isinstance(root, dict) else None
    if not isinstance(items, dict):
        return
    record = items.get(watcher.fixed_listing_id(lot))
    if not isinstance(record, dict):
        return

    # PENDING_BUDGET is not an outage. Keep it in P4 but retry on the next normal
    # scanner cycle instead of exponentially delaying it up to six hours.
    record["retry_count"] = 0
    cooldown = _budget_pending_cooldown_minutes()
    record["retry_after"] = (
        (run_now + timedelta(minutes=cooldown)).isoformat()
        if cooldown > 0
        else None
    )


def _fetch_external_with_fixed_ebay_reserve(
    page,
    candidate: watcher.ValuationCandidate,
    budgets: watcher.ValidationBudgets,
    diagnostics: watcher.ExternalMarketDiagnostics,
    now: datetime,
) -> watcher.ExternalMarketEvidence:
    total_cap = max(0, int(watcher.EBAY_MAX_CARDS_PER_RUN))
    reserve = _configured_fixed_ebay_reserve(total_cap)
    effective_cap = _effective_ebay_cap_for_candidate(
        candidate,
        total_cap=total_cap,
        fixed_reserve=reserve,
    )

    # watcher.fetch_external_market_evidence reads the module-global cap. The
    # scanner is single-threaded, so a tightly scoped temporary cap preserves the
    # existing function while reserving capacity for fixed candidates.
    previous_cap = watcher.EBAY_MAX_CARDS_PER_RUN
    watcher.EBAY_MAX_CARDS_PER_RUN = effective_cap
    try:
        return _ORIGINAL_FETCH_EXTERNAL(
            page,
            candidate,
            budgets,
            diagnostics,
            now,
        )
    finally:
        watcher.EBAY_MAX_CARDS_PER_RUN = previous_cap


def install_v4_external_coverage_drain() -> None:
    """Install bounded backlog-drain scheduling without changing V4 economics."""
    global _ORIGINAL_FETCH_EXTERNAL
    global _ORIGINAL_RECORD_FIXED_EXTERNAL_STATUS
    global _ORIGINAL_PREPARE_FIXED_QUEUE
    global _INSTALLED

    if _INSTALLED:
        return

    _ORIGINAL_FETCH_EXTERNAL = watcher.fetch_external_market_evidence
    _ORIGINAL_RECORD_FIXED_EXTERNAL_STATUS = watcher._record_fixed_external_status
    _ORIGINAL_PREPARE_FIXED_QUEUE = watcher._prepare_fixed_economic_queue

    watcher.fetch_external_market_evidence = _fetch_external_with_fixed_ebay_reserve
    watcher._record_fixed_external_status = (
        _record_fixed_external_status_with_budget_semantics
    )
    watcher._prepare_fixed_economic_queue = _prepare_fixed_queue_with_pending_migration

    total = max(0, int(watcher.EBAY_MAX_CARDS_PER_RUN))
    reserve = _configured_fixed_ebay_reserve(total)
    auction_cap = max(0, total - reserve)
    watcher.log(
        "External coverage drain enabled: "
        f"eBay SOLD total {total}/run | auctions max {auction_cap} | "
        f"fixed reserve {reserve} | budget-pending cooldown "
        f"{_budget_pending_cooldown_minutes()}m | provider-error backoff unchanged"
    )
    _INSTALLED = True
