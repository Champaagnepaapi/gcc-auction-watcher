from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import watcher
import v4_auction_item_discovery as auction_discovery
import v4_auction_pagination_stability as auction_stability


UPCOMING_AUCTION = "UPCOMING_AUCTION"
_START_FIELDS = (
    "startTime",
    "startAt",
    "startsAt",
    "auctionStartTime",
)
_UPCOMING_RENDERED_RE = re.compile(
    r"(?:\bEnch[èe]res?\s+[àa]\s+venir\b|"
    r"\bProgrammer\s+une\s+ench[èe]re\b|"
    r"\bUpcoming\s+auctions?\b|"
    r"\bSchedule\s+(?:a\s+)?bid\b)",
    re.I,
)

# Pagination stability captures the unwrapped item-level collector when its
# module is imported. The guard itself is imported from the stability installer,
# after item_discovery.discover_auction_api_lots has already been replaced by
# the stable wrapper, so capture the preserved inner collector here explicitly
# to avoid stable -> guard -> stable recursion.
_BASE_DISCOVER_AUCTION_API_LOTS = (
    auction_stability._ORIGINAL_DISCOVER_AUCTION_API_LOTS
)
_BASE_INSPECT_ITEM = watcher.inspect_item
_INSTALLED_V4 = False
_INSTALLED_GLOBAL = False


def _as_utc(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _reference_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def auction_start_time(row: Mapping[str, Any]) -> Optional[datetime]:
    """Read only explicit structured GCC auction-start fields.

    No missing field is interpreted as already-started or upcoming evidence.
    The guard blocks only when a provider timestamp explicitly proves a future
    start, preserving fail-closed identity/economic semantics without guessing.
    """

    for field in _START_FIELDS:
        parsed = _as_utc(row.get(field))
        if parsed is not None:
            return parsed
    return None


def is_upcoming_auction_row(
    row: Mapping[str, Any],
    *,
    observed_at: datetime,
) -> bool:
    raw_type = str(
        row.get("sellingTypeGroup") or row.get("sellingType") or ""
    ).strip().upper()
    if "AUCTION" not in raw_type:
        return False
    start_at = auction_start_time(row)
    if start_at is None:
        return False
    return start_at > _reference_utc(observed_at)


def rendered_page_proves_upcoming(body: object) -> bool:
    return bool(_UPCOMING_RENDERED_RE.search(str(body or "")))


class _FilteredResponse:
    def __init__(self, response: object, payload: object):
        self._response = response
        self._payload = payload
        self.headers = getattr(response, "headers", {})

    def raise_for_status(self):
        return self._response.raise_for_status()

    def json(self):
        return self._payload

    def __getattr__(self, name: str):
        return getattr(self._response, name)


def guarded_discover_auction_api_lots(
    *,
    max_minutes: Optional[int] = None,
    http_get=None,
    page_size: int = auction_discovery.AUCTION_API_PAGE_SIZE,
    max_pages: int = auction_discovery.AUCTION_API_MAX_PAGES,
    now: Optional[datetime] = None,
):
    """Remove explicitly future-start GCC rows before countdown/price handling.

    The underlying discovery still owns pagination, ENDING_SOON ordering,
    Pokemon/card/price filtering and coverage accounting. This wrapper only
    prevents a starting price/countdown-to-start from becoming a live auction.
    """

    reference = _reference_utc(now or datetime.now(timezone.utc))
    getter = http_get or watcher.requests.get
    excluded = 0

    def guarded_get(url, **kwargs):
        nonlocal excluded
        response = getter(url, **kwargs)
        payload = response.json()
        if not isinstance(payload, Mapping):
            return _FilteredResponse(response, payload)
        results = payload.get("results")
        if not isinstance(results, list):
            return _FilteredResponse(response, payload)

        kept = []
        for row in results:
            if isinstance(row, Mapping) and is_upcoming_auction_row(
                row, observed_at=reference
            ):
                excluded += 1
                continue
            kept.append(row)
        if len(kept) == len(results):
            return _FilteredResponse(response, payload)
        filtered = copy.deepcopy(dict(payload))
        filtered["results"] = kept
        return _FilteredResponse(response, filtered)

    result = _BASE_DISCOVER_AUCTION_API_LOTS(
        max_minutes=max_minutes,
        http_get=guarded_get,
        page_size=page_size,
        max_pages=max_pages,
        now=reference,
    )
    setattr(result.coverage, "auction_upcoming_excluded", excluded)
    if excluded:
        watcher.log(
            "Upcoming auction guard: "
            f"{excluded} future-start row(s) excluded before valuation"
        )
    return result


def guarded_inspect_item(page, lot: watcher.Lot, *, log_listing_errors: bool = True):
    inspected = _BASE_INSPECT_ITEM(
        page,
        lot,
        log_listing_errors=log_listing_errors,
    )
    if (
        inspected.source_type == "auction"
        and rendered_page_proves_upcoming(inspected.body)
    ):
        # The visible amount on this page is a starting price, not a current bid;
        # the visible timer is a countdown to the start, not to the end.
        inspected.current_price = None
        inspected.minutes_to_end = None
        inspected.end_text = ""
        setattr(inspected, "auction_state", UPCOMING_AUCTION)
        watcher.log(
            "Upcoming auction guard: rendered GCC page proves auction not started; "
            f"starting price/timer ignored | {inspected.url}"
        )
    return inspected


def install_v4_upcoming_auction_guard() -> None:
    """Install on V4 discovery + legacy/final page rechecks."""

    global _INSTALLED_V4
    if _INSTALLED_V4:
        return
    # Pagination stability captured the base discovery at import time. Point its
    # inner pass at the guarded base so future-start rows are removed before the
    # ENDING_SOON horizon and candidate union are computed.
    auction_stability._ORIGINAL_DISCOVER_AUCTION_API_LOTS = (
        guarded_discover_auction_api_lots
    )
    watcher.inspect_item = guarded_inspect_item
    _INSTALLED_V4 = True


def install_global_upcoming_auction_guard() -> None:
    """Apply the same structured start gate to Global GCC marketplace scan."""

    global _INSTALLED_GLOBAL
    if _INSTALLED_GLOBAL:
        return
    import v4_global_marketplace_discovery as global_discovery
    import v4_global_marketplace_scan as global_scan

    original = global_discovery.gcc_listing_from_row

    def guarded_gcc_listing_from_row(row, *, observed_at):
        if is_upcoming_auction_row(row, observed_at=observed_at):
            return None
        return original(row, observed_at=observed_at)

    global_discovery.gcc_listing_from_row = guarded_gcc_listing_from_row
    # marketplace_scan imports the function into its module namespace.
    global_scan.gcc_listing_from_row = guarded_gcc_listing_from_row
    _INSTALLED_GLOBAL = True
