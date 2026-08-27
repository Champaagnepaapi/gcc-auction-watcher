from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable, Optional

import watcher
import v4_auction_item_discovery as item_discovery


STABLE_AUCTION_API_PAGE_SIZE = 100
STABLE_AUCTION_API_MAX_PASSES = 3
STABLE_UNION_REASON = "AUCTION_API_STABLE_SNAPSHOT_UNION"
UNSTABLE_REASON = "auction API live pagination drift did not stabilize"

_ORIGINAL_DISCOVER_AUCTION_API_LOTS = item_discovery.discover_auction_api_lots
_INSTALLED = False


def discover_auction_api_lots_stable(
    *,
    max_minutes: Optional[int] = None,
    http_get=None,
    page_size: int = STABLE_AUCTION_API_PAGE_SIZE,
    max_pages: int = item_discovery.AUCTION_API_MAX_PAGES,
    now: Optional[datetime] = None,
    max_passes: int = STABLE_AUCTION_API_MAX_PASSES,
    discover_func: Optional[Callable[..., item_discovery.AuctionApiDiscoveryResult]] = None,
) -> item_discovery.AuctionApiDiscoveryResult:
    """Union repeated anchored API snapshots until pagination stops losing rows.

    GCC's ENDING_SOON inventory is live: while page-number pagination advances,
    an auction can expire and shift later rows one page backwards. A single
    internally monotonic pass can therefore silently skip one row. We use a
    fixed time anchor, a larger page size, and repeated read-only snapshots.

    The union is returned only after a later pass adds no new candidate URL. If
    growth still occurs after the bounded number of passes, coverage fails
    closed so the existing complete legacy fallback remains authoritative.
    """

    if max_passes < 2:
        raise ValueError("stable auction discovery requires at least 2 passes")

    discover = discover_func or _ORIGINAL_DISCOVER_AUCTION_API_LOTS
    anchor = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    union: dict[str, watcher.Lot] = {}
    last_result: Optional[item_discovery.AuctionApiDiscoveryResult] = None

    for pass_number in range(1, max_passes + 1):
        result = discover(
            max_minutes=max_minutes,
            http_get=http_get,
            page_size=page_size,
            max_pages=max_pages,
            now=anchor,
        )
        last_result = result
        if not result.complete:
            return result

        before = len(union)
        for lot in result.lots:
            url = str(getattr(lot, "url", "") or "").strip()
            if url:
                union.setdefault(url, lot)
        added = len(union) - before

        if pass_number >= 2 and added == 0:
            if len(union) == len(result.lots):
                return result
            watcher.log(
                "Auction API stability guard: union stable after "
                f"{pass_number} pass(es), {len(union)} unique candidate(s)"
            )
            return replace(
                result,
                lots=list(union.values()),
                reason=STABLE_UNION_REASON,
            )

        if pass_number >= 2:
            watcher.log(
                "Auction API stability guard: live pagination drift detected, "
                f"pass {pass_number} added {added} candidate(s)"
            )

    assert last_result is not None
    last_result.coverage.mark_incomplete(UNSTABLE_REASON, watcher.END_NO_PROGRESS)
    setattr(last_result.coverage, "_auction_scope_complete", False)
    setattr(
        last_result.coverage,
        "auction_scope_status",
        item_discovery.FALLBACK_SCOPE_STATUS,
    )
    return replace(
        last_result,
        lots=[],
        complete=False,
        scope_status=item_discovery.FALLBACK_SCOPE_STATUS,
        order_verified=False,
        reason=UNSTABLE_REASON,
    )


def install_v4_auction_pagination_stability() -> None:
    """Install the stability wrapper plus the future-start auction safety gate."""

    global _INSTALLED
    if _INSTALLED:
        return
    item_discovery.discover_auction_api_lots = discover_auction_api_lots_stable
    # Keep one canonical auction collector. The add-on only removes rows whose
    # structured start timestamp explicitly proves that bidding has not begun,
    # and also protects rendered legacy/final-page rechecks.
    from v4_upcoming_auction_guard import install_v4_upcoming_auction_guard

    install_v4_upcoming_auction_guard()
    _INSTALLED = True
