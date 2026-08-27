from __future__ import annotations

import os
from typing import Optional

import watcher


URGENT_AUCTION_MINUTES = 5
SOON_AUCTION_MINUTES = 12
DEFAULT_AUCTION_EVALUATION_CAP = 360
MIN_AUCTION_EVALUATION_CAP = 120
MAX_AUCTION_EVALUATION_CAP = 600
CAP_ENV = "V4_AUCTION_EVALUATION_CAP"

_ORIGINAL_REGISTER_CANDIDATES = watcher.EconomicCoverageAudit.register_candidates
_INSTALLED = False


def configured_auction_evaluation_cap() -> int:
    """Return the bounded V4 auction evaluation cap.

    The previous production cap was 120. Never allow an accidental environment
    override to reduce coverage below that historical floor, and retain a hard
    upper safety bound so a malformed value cannot create an unbounded run.
    """

    raw = os.getenv(CAP_ENV, str(DEFAULT_AUCTION_EVALUATION_CAP)).strip()
    try:
        requested = int(raw)
    except ValueError:
        requested = DEFAULT_AUCTION_EVALUATION_CAP
    return max(
        MIN_AUCTION_EVALUATION_CAP,
        min(MAX_AUCTION_EVALUATION_CAP, requested),
    )


def auction_priority_bucket(lot: watcher.Lot) -> int:
    """Explicit economic scheduling tier; never an identity/evidence decision."""

    minutes = lot.minutes_to_end
    if minutes is None:
        return 3
    if minutes <= URGENT_AUCTION_MINUTES:
        return 0
    if minutes <= SOON_AUCTION_MINUTES:
        return 1
    if minutes <= watcher.MAX_AUCTION_MINUTES:
        return 2
    return 3


def auction_priority_key(lot: watcher.Lot) -> tuple[int, int, float, str]:
    minutes = lot.minutes_to_end
    price = lot.current_price
    return (
        auction_priority_bucket(lot),
        minutes if minutes is not None else 999999,
        price if price is not None else 999999.0,
        lot.url or lot.title,
    )


def prioritized_register_candidates(
    audit: watcher.EconomicCoverageAudit,
    lots: list[watcher.Lot],
    *,
    discovered_listings: Optional[int] = None,
    valuation_cap: Optional[int] = None,
) -> None:
    """Make auction scheduling tiers explicit at the economic-cap boundary.

    `watcher.scan()` already sorts auctions by remaining time before applying the
    cap. This wrapper makes the required <=5 / <=12 / <=60 ordering an explicit
    invariant exactly where candidates are registered, without changing card
    identity, valuation, market evidence, notification semantics or provider
    budgets. The list is intentionally sorted in place because watcher slices
    that same list immediately after registration.
    """

    if str(audit.label or "").strip().upper() == "AUCTIONS":
        lots.sort(key=auction_priority_key)
    return _ORIGINAL_REGISTER_CANDIDATES(
        audit,
        lots,
        discovered_listings=discovered_listings,
        valuation_cap=valuation_cap,
    )


def install_v4_auction_priority_budget() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    cap = configured_auction_evaluation_cap()
    watcher.MAX_AUCTION_CANDIDATES = cap
    watcher.EconomicCoverageAudit.register_candidates = prioritized_register_candidates
    watcher.log(
        "Auction economic scheduling: "
        f"priority <= {URGENT_AUCTION_MINUTES} min, then <= {SOON_AUCTION_MINUTES} min, "
        f"then <= {watcher.MAX_AUCTION_MINUTES} min | cap={cap}"
    )
    _INSTALLED = True
