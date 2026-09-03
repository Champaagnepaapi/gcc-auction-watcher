from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

import watcher
import v4_auction_item_discovery as auction_discovery


UPCOMING_AUCTION = "UPCOMING_AUCTION"
LIVE_AUCTION = "LIVE_AUCTION"
STARTED_STRUCTURED = "STARTED_STRUCTURED"
START_UNPROVEN = "START_UNPROVEN"

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
_LIVE_ACTION_RE = re.compile(
    r"(?:\bEnch[ée]rir\b|\bPlace\s+(?:a\s+)?bid\b|\bBid\s+now\b)",
    re.I,
)
_END_LABEL_RE = re.compile(
    r"(?:\bFin\s+(?:le|à)\b|\bEnds?\s+(?:on|at|in)\b|\bAuction\s+ends?\b)",
    re.I,
)

_DEFAULT_DISCOVER_AUCTION_API_LOTS = auction_discovery.discover_auction_api_lots
_DEFAULT_INSPECT_ITEM = watcher.inspect_item
_DEFAULT_COLLECT_LOTS_FROM_LISTING = watcher.collect_lots_from_listing
_BASE_DISCOVER_AUCTION_API_LOTS: Optional[Callable[..., object]] = None
_BASE_INSPECT_ITEM: Optional[Callable[..., object]] = None
_BASE_COLLECT_LOTS_FROM_LISTING: Optional[Callable[..., object]] = None
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


def rendered_page_proves_live(body: object) -> bool:
    """Require both a live bid action and explicit auction-end semantics."""

    text = str(body or "")
    if rendered_page_proves_upcoming(text):
        return False
    return bool(_LIVE_ACTION_RE.search(text) and _END_LABEL_RE.search(text))


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


def _active_collect_base() -> Callable[..., object]:
    return _BASE_COLLECT_LOTS_FROM_LISTING or _DEFAULT_COLLECT_LOTS_FROM_LISTING


def _lot_stable_id(lot: watcher.Lot) -> str:
    url = str(getattr(lot, "url", "") or "").rstrip("/")
    return url.rsplit("/", 1)[-1] if "/" in url else ""


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
    not begun. Rows with an explicit past/current start are marked so the main
    collector can trust them without another rendered-page probe. Rows with no
    explicit start proof remain START_UNPROVEN and must be verified before any
    timer/starting-price can enter economic evaluation.
    """

    reference = _reference_utc(now or datetime.now(timezone.utc))
    getter = http_get or watcher.requests.get
    excluded_ids: set[str] = set()
    started_ids: set[str] = set()
    unproven_ids: set[str] = set()

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
            if not stable_id:
                kept.append(row)
                continue

            start_at = auction_start_time(row)
            if start_at is not None and start_at > reference:
                excluded_ids.add(stable_id)
                started_ids.discard(stable_id)
                unproven_ids.discard(stable_id)
                continue

            if start_at is not None:
                if stable_id not in excluded_ids and stable_id not in unproven_ids:
                    started_ids.add(stable_id)
            elif stable_id not in excluded_ids:
                started_ids.discard(stable_id)
                unproven_ids.add(stable_id)
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

    # A row can appear in repeated stabilized snapshots. Any future-start proof
    # remains authoritative even if another pass omitted the start field.
    result.lots = [
        lot for lot in result.lots if _lot_stable_id(lot) not in excluded_ids
    ]
    for lot in result.lots:
        stable_id = _lot_stable_id(lot)
        state = STARTED_STRUCTURED if stable_id in started_ids else START_UNPROVEN
        setattr(lot, "auction_start_state", state)

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


def _probe_rendered_auction_state(page, lot: watcher.Lot) -> str:
    """Classify an unproven timer using the rendered item page, fail-closed."""

    try:
        page.goto(
            lot.url,
            wait_until="domcontentloaded",
            timeout=watcher.NAV_TIMEOUT,
        )
        page.wait_for_timeout(650)
        body = page.locator("body").inner_text(timeout=watcher.TEXT_TIMEOUT)
    except Exception as error:
        watcher.log(
            "Upcoming auction guard: rendered state verification failed "
            f"{type(error).__name__} | {lot.url}"
        )
        return START_UNPROVEN

    if rendered_page_proves_upcoming(body):
        return UPCOMING_AUCTION
    if rendered_page_proves_live(body):
        return LIVE_AUCTION
    return START_UNPROVEN


def guarded_collect_lots_from_listing(
    page,
    url: str,
    source_type: str,
    run_diagnostics: Optional[watcher.RunDiagnostics] = None,
    **kwargs,
) -> list[watcher.Lot]:
    """Block timer-bearing auctions whose live state is not actually proven.

    This closes the API bypass that produced Braixen/Altaria/Poochyena/Swablu
    false EXTERNAL_RESCUE alerts: V4's main loop only calls inspect_item when a
    listing timer is missing. API rows already carrying a countdown therefore
    skipped the rendered-page UPCOMING guard. We verify only those timer-bearing
    auctions that lack explicit structured start proof; ambiguous/error states
    are excluded from economic evaluation rather than guessed live.
    """

    lots = list(
        _active_collect_base()(
            page,
            url,
            source_type,
            run_diagnostics,
            **kwargs,
        )
    )
    if source_type != "auction":
        return lots

    kept: list[watcher.Lot] = []
    rendered_upcoming = 0
    rendered_live = 0
    unproven_excluded = 0

    for lot in lots:
        # Timerless lots already take the existing inspect_item fallback path in
        # watcher.py, which is itself wrapped by guarded_inspect_item.
        if lot.minutes_to_end is None:
            kept.append(lot)
            continue

        if getattr(lot, "auction_start_state", "") == STARTED_STRUCTURED:
            kept.append(lot)
            continue

        state = _probe_rendered_auction_state(page, lot)
        setattr(lot, "auction_state", state)

        if state == LIVE_AUCTION:
            rendered_live += 1
            kept.append(lot)
            continue

        if state == UPCOMING_AUCTION:
            rendered_upcoming += 1
            lot.current_price = None
            lot.minutes_to_end = None
            lot.end_text = ""
            watcher.log(
                "Upcoming auction guard: timer-bearing candidate is UPCOMING; "
                f"starting price/countdown excluded | {lot.url}"
            )
        else:
            unproven_excluded += 1
            watcher.log(
                "Upcoming auction guard: timer-bearing candidate live state "
                f"unproven -> fail-closed exclusion | {lot.url}"
            )

        coverage = (
            run_diagnostics.auction_coverage
            if run_diagnostics is not None
            else None
        )
        if coverage is not None:
            coverage.record_terminal(
                lot.url,
                watcher.ACCOUNT_EXCLUDED_BY_RULES
                if state == UPCOMING_AUCTION
                else watcher.ACCOUNT_PARSE_FAILURE,
            )

    if run_diagnostics is not None:
        setattr(
            run_diagnostics,
            "auction_rendered_upcoming_excluded",
            getattr(run_diagnostics, "auction_rendered_upcoming_excluded", 0)
            + rendered_upcoming,
        )
        setattr(
            run_diagnostics,
            "auction_rendered_live_verified",
            getattr(run_diagnostics, "auction_rendered_live_verified", 0)
            + rendered_live,
        )
        setattr(
            run_diagnostics,
            "auction_rendered_state_unproven_excluded",
            getattr(
                run_diagnostics,
                "auction_rendered_state_unproven_excluded",
                0,
            )
            + unproven_excluded,
        )

    return kept


def install_v4_upcoming_auction_guard() -> None:
    """Wrap current auction discovery, main collector, and rendered rechecks."""

    global _BASE_DISCOVER_AUCTION_API_LOTS
    global _BASE_INSPECT_ITEM
    global _BASE_COLLECT_LOTS_FROM_LISTING
    global _INSTALLED_V4
    if _INSTALLED_V4:
        return

    # Capture at install time, not import time. This is intentionally installed
    # after current order-drift + stable-pagination hardening, so those layers
    # remain authoritative underneath this narrow future-start exclusion.
    _BASE_DISCOVER_AUCTION_API_LOTS = auction_discovery.discover_auction_api_lots
    _BASE_INSPECT_ITEM = watcher.inspect_item
    _BASE_COLLECT_LOTS_FROM_LISTING = watcher.collect_lots_from_listing
    auction_discovery.discover_auction_api_lots = guarded_discover_auction_api_lots
    watcher.inspect_item = guarded_inspect_item
    watcher.collect_lots_from_listing = guarded_collect_lots_from_listing
    _INSTALLED_V4 = True
