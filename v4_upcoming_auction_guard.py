from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

import watcher
import v4_auction_item_discovery as auction_discovery


UPCOMING_AUCTION = "UPCOMING_AUCTION"
_START_FIELDS = (
    "startTime",
    "startAt",
    "startsAt",
    "auctionStartTime",
)
_UPCOMING_ACTION_RE = re.compile(
    r"(?:\bProgrammer\s+une\s+ench[èe]re\b|\bSchedule\s+(?:a\s+)?bid\b)",
    re.I,
)
_UPCOMING_HEADING_RE = re.compile(
    r"(?:\bEnch[èe]res?\s+[àa]\s+venir\b|\bUpcoming\s+auctions?\b)",
    re.I,
)
_START_LABEL_RE = re.compile(
    r"(?:\bD[ée]but\s+(?:le|à)\b|\bStarts?\s+(?:on|at)\b|\bAuction\s+starts?\b)",
    re.I,
)

_DEFAULT_DISCOVER_AUCTION_API_LOTS = auction_discovery.discover_auction_api_lots
_DEFAULT_INSPECT_ITEM = watcher.inspect_item
_BASE_DISCOVER_AUCTION_API_LOTS: Optional[Callable[..., object]] = None
_BASE_INSPECT_ITEM: Optional[Callable[..., object]] = None
_INSTALLED_V4 = False


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
    """Read only explicit structured GCC auction-start fields."""

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
    """Return true only when GCC explicitly proves an AUCTION starts later."""

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
    """Use strong rendered-page evidence without trusting a navigation label alone."""

    text = str(body or "")
    if _UPCOMING_ACTION_RE.search(text):
        return True
    return bool(_UPCOMING_HEADING_RE.search(text) and _START_LABEL_RE.search(text))


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


def _active_discover_base() -> Callable[..., object]:
    return _BASE_DISCOVER_AUCTION_API_LOTS or _DEFAULT_DISCOVER_AUCTION_API_LOTS


def _active_inspect_base() -> Callable[..., object]:
    return _BASE_INSPECT_ITEM or _DEFAULT_INSPECT_ITEM


def guarded_discover_auction_api_lots(
    *,
    max_minutes: Optional[int] = None,
    http_get=None,
    page_size: int = auction_discovery.AUCTION_API_PAGE_SIZE,
    max_pages: int = auction_discovery.AUCTION_API_MAX_PAGES,
    now: Optional[datetime] = None,
):
    """Remove proven future-start rows before countdown/price interpretation.

    The current production collector stack still owns order-drift recovery,
    stable pagination, Pokemon/card/price filtering and coverage semantics. This
    wrapper only hides rows whose structured start timestamp proves bidding has
    not begun. Rows without a stable GCC id are deliberately left untouched so
    the canonical collector can fail closed on malformed provider data.
    """

    reference = _reference_utc(now or datetime.now(timezone.utc))
    getter = http_get or watcher.requests.get
    excluded_ids: set[str] = set()

    def guarded_get(url, **kwargs):
        response = getter(url, **kwargs)
        payload = response.json()
        if not isinstance(payload, Mapping):
            return _FilteredResponse(response, payload)
        results = payload.get("results")
        if not isinstance(results, list):
            return _FilteredResponse(response, payload)

        kept = []
        for row in results:
            if not isinstance(row, Mapping):
                kept.append(row)
                continue
            result_id = row.get("id")
            stable_id = result_id.strip() if isinstance(result_id, str) else ""
            if stable_id and is_upcoming_auction_row(row, observed_at=reference):
                excluded_ids.add(stable_id)
                continue
            kept.append(row)

        if len(kept) == len(results):
            return _FilteredResponse(response, payload)
        filtered = copy.deepcopy(dict(payload))
        filtered["results"] = kept
        return _FilteredResponse(response, filtered)

    result = _active_discover_base()(
        max_minutes=max_minutes,
        http_get=guarded_get,
        page_size=page_size,
        max_pages=max_pages,
        now=reference,
    )
    setattr(result.coverage, "auction_upcoming_excluded", len(excluded_ids))
    if excluded_ids:
        watcher.log(
            "Upcoming auction guard: "
            f"{len(excluded_ids)} future-start row(s) excluded before valuation"
        )
    return result


def guarded_inspect_item(page, lot: watcher.Lot, *, log_listing_errors: bool = True):
    inspected = _active_inspect_base()(
        page,
        lot,
        log_listing_errors=log_listing_errors,
    )
    if (
        inspected is not None
        and inspected.source_type == "auction"
        and rendered_page_proves_upcoming(inspected.body)
    ):
        # On an upcoming page the amount is a starting price and the visible
        # countdown is to the start, not to auction end. Neither may enter V4
        # valuation or the <=5 minute final-check lane.
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
    """Wrap the already-installed production collector and rendered rechecks."""

    global _BASE_DISCOVER_AUCTION_API_LOTS
    global _BASE_INSPECT_ITEM
    global _INSTALLED_V4
    if _INSTALLED_V4:
        return

    # Capture at install time, not import time. This is intentionally installed
    # after current order-drift + stable-pagination hardening, so those layers
    # remain authoritative underneath this narrow future-start exclusion.
    _BASE_DISCOVER_AUCTION_API_LOTS = auction_discovery.discover_auction_api_lots
    _BASE_INSPECT_ITEM = watcher.inspect_item
    auction_discovery.discover_auction_api_lots = guarded_discover_auction_api_lots
    watcher.inspect_item = guarded_inspect_item
    _INSTALLED_V4 = True
