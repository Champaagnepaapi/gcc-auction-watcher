from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Optional

import watcher


AUCTION_INDEX_URL = f"{watcher.BASE}/filtres/auctions"
AUCTION_API_URL = watcher.GCC_ON_SALE_ITEMS_API_URL
PRIMARY_PROTOCOL = "GCC_PUBLIC_API_AUCTION_ENDING_SOON_ITEM_LEVEL"
PRIMARY_SCOPE_STATUS = "COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS"
FALLBACK_SCOPE_STATUS = "LEGACY_LIVE_SALES_FALLBACK"
PRIMARY_END_REASON = "AUCTION_HORIZON_CROSSED_IN_ENDING_SOON_ORDER"
PRIMARY_EXHAUSTED_REASON = "AUCTION_API_EXHAUSTED"
PRIMARY_MODE = "AUCTION_API_ITEM_LEVEL"
FALLBACK_MODE = "LEGACY_LIVE_SALES"
AUCTION_API_PAGE_SIZE = 24
AUCTION_API_MAX_PAGES = 100
END_TIME_ORDER_TOLERANCE_SECONDS = 2.0

_ORIGINAL_COLLECT_LIVE_AUCTION_URLS = watcher.collect_live_auction_urls
_ORIGINAL_COLLECT_LOTS_FROM_LISTING = watcher.collect_lots_from_listing
_ORIGINAL_COVERAGE_STATUS_GETTER = watcher.CoverageAudit.status.fget
_ORIGINAL_LOG_SCAN_COVERAGE = watcher.log_scan_coverage
_INSTALLED = False


@dataclass(frozen=True)
class ParsedAuctionEnd:
    at: datetime
    minutes: int
    text: str


@dataclass
class AuctionApiDiscoveryResult:
    lots: list[watcher.Lot]
    coverage: watcher.CoverageAudit
    complete: bool
    scope_status: str
    rows_seen: int
    timers_parsed: int
    timerless_eligible: int
    order_verified: bool
    threshold_crossed: bool
    api_total: Optional[int]
    reason: str = ""


def _parse_api_end_time(
    raw: object,
    *,
    now: Optional[datetime] = None,
) -> Optional[ParsedAuctionEnd]:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    seconds = max(0.0, (parsed - current).total_seconds())
    minutes = int(math.ceil(seconds / 60.0))
    return ParsedAuctionEnd(
        at=parsed,
        minutes=minutes,
        text=parsed.strftime("%d/%m %H:%M UTC"),
    )


def _api_order_is_valid(previous: Optional[datetime], current: datetime) -> bool:
    if previous is None:
        return True
    return (
        current - previous
    ).total_seconds() >= -END_TIME_ORDER_TOLERANCE_SECONDS


def _auction_api_lot(
    result: dict,
    item_url: str,
    coverage: watcher.CoverageAudit,
    parsed_end: ParsedAuctionEnd,
) -> Optional[watcher.Lot]:
    # GCC uses the same structured item schema on this endpoint for fixed and
    # auction rows. Reuse V4's existing parser so Pokemon/card/0-100 filtering
    # is exactly the same as the already-audited fixed-price path.
    lot = watcher._gcc_fixed_result_to_lot(
        result,
        item_url,
        coverage,
        min_price=watcher.MIN_PRICE,
        max_price=watcher.MAX_PRICE,
    )
    if lot is None:
        return None
    return replace(
        lot,
        source_type="auction",
        sale_name="GCC auctions / ending soon",
        minutes_to_end=parsed_end.minutes,
        end_text=parsed_end.text,
    )


def discover_auction_api_lots(
    *,
    max_minutes: Optional[int] = None,
    http_get=None,
    page_size: int = AUCTION_API_PAGE_SIZE,
    max_pages: int = AUCTION_API_MAX_PAGES,
    now: Optional[datetime] = None,
) -> AuctionApiDiscoveryResult:
    horizon = (
        watcher.MAX_AUCTION_MINUTES
        if max_minutes is None
        else max(0, int(max_minutes))
    )
    coverage = watcher.CoverageAudit("AUCTIONS", watcher.AUCTION_DISCOVERY_FILTERS)
    coverage.protocol = PRIMARY_PROTOCOL
    getter = http_get or watcher.requests.get
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    if page_size <= 0 or max_pages <= 0:
        coverage.record_malformed("invalid auction API pagination configuration")
        return AuctionApiDiscoveryResult(
            [], coverage, False, FALLBACK_SCOPE_STATUS, 0, 0, 0,
            False, False, None, "invalid auction API pagination configuration"
        )

    lots: dict[str, watcher.Lot] = {}
    rows_seen = 0
    timers_parsed = 0
    timerless_eligible = 0
    threshold_crossed = False
    api_total: Optional[int] = None
    previous_end: Optional[datetime] = None
    next_page = 1

    for _ in range(max_pages):
        page_number = next_page
        page_label = (
            f"{AUCTION_API_URL}?sellingTypeGroup=AUCTION&sortType=ENDING_SOON"
            f"&status=ON_SALE&page={page_number}&limit={page_size}"
        )
        coverage.begin_page(page_label)
        params = {
            "sellingTypeGroup": "AUCTION",
            "sortType": "ENDING_SOON",
            "status": "ON_SALE",
            "includeCounts": "true" if page_number == 1 else "false",
            "includeSavedSearchMatch": "true",
            "page": page_number,
            "limit": page_size,
        }

        response = None
        payload = None
        for attempt in range(watcher.GCC_PAGE_RETRIES + 1):
            try:
                response = getter(
                    AUCTION_API_URL,
                    params=params,
                    headers={
                        "Accept": "application/json",
                        "x-device-platform": "web",
                    },
                    timeout=max(1.0, watcher.NAV_TIMEOUT / 1000),
                )
                response.raise_for_status()
                payload = response.json()
                break
            except Exception as error:
                if attempt < watcher.GCC_PAGE_RETRIES:
                    coverage.record_retry()
                    watcher.log(
                        f"Retry GCC auction API {attempt + 1}/"
                        f"{watcher.GCC_PAGE_RETRIES}: {type(error).__name__} "
                        f"| page {page_number}"
                    )
                    continue
                coverage.record_page_failure(
                    f"auction API page {page_number} failed after "
                    f"{watcher.GCC_PAGE_RETRIES} retries: {type(error).__name__}"
                )
                return AuctionApiDiscoveryResult(
                    [], coverage, False, FALLBACK_SCOPE_STATUS,
                    rows_seen, timers_parsed, timerless_eligible,
                    False, threshold_crossed, api_total,
                    f"auction API page {page_number} failed",
                )

        if page_number == 1 and response is not None:
            watcher._log_gcc_numeric_rate_limits(response)
        if not isinstance(payload, dict):
            coverage.record_malformed(
                f"auction API page {page_number}: payload is not an object"
            )
            return AuctionApiDiscoveryResult(
                [], coverage, False, FALLBACK_SCOPE_STATUS,
                rows_seen, timers_parsed, timerless_eligible,
                False, threshold_crossed, api_total,
                "auction API payload malformed",
            )

        info = payload.get("info")
        results = payload.get("results")
        if not isinstance(info, dict) or not isinstance(results, list):
            coverage.record_malformed(
                f"auction API page {page_number}: missing info/results"
            )
            return AuctionApiDiscoveryResult(
                [], coverage, False, FALLBACK_SCOPE_STATUS,
                rows_seen, timers_parsed, timerless_eligible,
                False, threshold_crossed, api_total,
                "auction API info/results missing",
            )
        if info.get("currentPage") != page_number:
            coverage.record_malformed(
                f"auction API did not advance: requested {page_number}, "
                f"received {info.get('currentPage')}"
            )
            return AuctionApiDiscoveryResult(
                [], coverage, False, FALLBACK_SCOPE_STATUS,
                rows_seen, timers_parsed, timerless_eligible,
                False, threshold_crossed, api_total,
                "auction API pagination did not advance",
            )

        if page_number == 1:
            counts = info.get("counts")
            if isinstance(counts, dict):
                raw_total = counts.get("total")
                if isinstance(raw_total, int) and not isinstance(raw_total, bool):
                    api_total = max(0, raw_total)

        row_ids: list[str] = []
        keyed_results: list[tuple[str, dict]] = []
        for result in results:
            if not isinstance(result, dict):
                coverage.record_unkeyed_row("auction API row is not an object")
                continue
            result_id = result.get("id")
            if not isinstance(result_id, str) or not result_id.strip():
                coverage.record_unkeyed_row(
                    "auction API row has no stable GCC id"
                )
                continue
            item_url = f"{watcher.BASE}/item/{result_id.strip()}"
            row_ids.append(item_url)
            keyed_results.append((item_url, result))

        previous_unique = coverage.unique_listings
        coverage.record_page_success(
            page_label,
            row_ids,
            expected_total=api_total if page_number == 1 else None,
            expected_total_scope=(
                watcher.EXPECTED_TOTAL_DIFFERENT_SCOPE
                if api_total is not None and page_number == 1
                else None
            ),
            page_size=page_size,
            detect_repeated_page=True,
        )
        rows_seen += len(row_ids)
        if coverage.pagination_end_reason == watcher.END_REPEATED_PAGE:
            return AuctionApiDiscoveryResult(
                [], coverage, False, FALLBACK_SCOPE_STATUS,
                rows_seen, timers_parsed, timerless_eligible,
                False, threshold_crossed, api_total,
                "auction API repeated page",
            )
        if row_ids and coverage.unique_listings == previous_unique:
            coverage.mark_incomplete(
                "auction API page produced no new stable ids",
                watcher.END_NO_PROGRESS,
            )
            return AuctionApiDiscoveryResult(
                [], coverage, False, FALLBACK_SCOPE_STATUS,
                rows_seen, timers_parsed, timerless_eligible,
                False, threshold_crossed, api_total,
                "auction API no progress",
            )

        page_has_missing_end = False
        for item_url, result in keyed_results:
            parsed_end = _parse_api_end_time(result.get("endTime"), now=current_time)
            if parsed_end is None:
                page_has_missing_end = True
                continue
            timers_parsed += 1
            if not _api_order_is_valid(previous_end, parsed_end.at):
                coverage.mark_incomplete(
                    "auction API ENDING_SOON order is not monotonic",
                    watcher.END_MALFORMED_RESPONSE,
                )
                return AuctionApiDiscoveryResult(
                    [], coverage, False, FALLBACK_SCOPE_STATUS,
                    rows_seen, timers_parsed, timerless_eligible,
                    False, threshold_crossed, api_total,
                    "auction API ending-soon order invalid",
                )
            previous_end = parsed_end.at

            lot = _auction_api_lot(result, item_url, coverage, parsed_end)
            if parsed_end.minutes > horizon:
                threshold_crossed = True
                if lot is not None:
                    coverage.record_terminal(
                        item_url, watcher.ACCOUNT_EXCLUDED_BY_RULES
                    )
                continue
            if lot is not None:
                lots.setdefault(item_url, lot)

        if page_has_missing_end:
            coverage.mark_incomplete(
                "auction API row missing/invalid endTime",
                watcher.END_MALFORMED_RESPONSE,
            )
            return AuctionApiDiscoveryResult(
                [], coverage, False, FALLBACK_SCOPE_STATUS,
                rows_seen, timers_parsed, timerless_eligible,
                False, threshold_crossed, api_total,
                "auction API endTime missing",
            )

        if threshold_crossed:
            coverage.pagination_end_reason = PRIMARY_END_REASON
            setattr(coverage, "_auction_scope_complete", True)
            setattr(coverage, "auction_scope_status", PRIMARY_SCOPE_STATUS)
            return AuctionApiDiscoveryResult(
                list(lots.values()), coverage, True, PRIMARY_SCOPE_STATUS,
                rows_seen, timers_parsed, timerless_eligible,
                True, True, api_total, PRIMARY_END_REASON,
            )

        raw_next = info.get("nextPage")
        if raw_next in {None, False, "", 0}:
            coverage.pagination_end_reason = PRIMARY_EXHAUSTED_REASON
            setattr(coverage, "_auction_scope_complete", True)
            setattr(coverage, "auction_scope_status", PRIMARY_SCOPE_STATUS)
            return AuctionApiDiscoveryResult(
                list(lots.values()), coverage, True, PRIMARY_SCOPE_STATUS,
                rows_seen, timers_parsed, timerless_eligible,
                True, False, api_total, PRIMARY_EXHAUSTED_REASON,
            )
        if not isinstance(raw_next, int) or isinstance(raw_next, bool):
            coverage.record_malformed("auction API nextPage is invalid")
            return AuctionApiDiscoveryResult(
                [], coverage, False, FALLBACK_SCOPE_STATUS,
                rows_seen, timers_parsed, timerless_eligible,
                False, threshold_crossed, api_total,
                "auction API nextPage invalid",
            )
        if raw_next <= page_number:
            coverage.mark_incomplete(
                "auction API nextPage did not advance",
                watcher.END_NO_PROGRESS,
            )
            return AuctionApiDiscoveryResult(
                [], coverage, False, FALLBACK_SCOPE_STATUS,
                rows_seen, timers_parsed, timerless_eligible,
                False, threshold_crossed, api_total,
                "auction API nextPage did not advance",
            )
        next_page = raw_next

    coverage.mark_incomplete(
        f"auction API safety limit {max_pages} pages reached",
        watcher.END_MAX_PAGE_LIMIT,
    )
    return AuctionApiDiscoveryResult(
        [], coverage, False, FALLBACK_SCOPE_STATUS,
        rows_seen, timers_parsed, timerless_eligible,
        False, threshold_crossed, api_total,
        f"auction API safety limit {max_pages} pages reached",
    )


def _attach_primary_result(
    run_diagnostics: Optional[watcher.RunDiagnostics],
    result: AuctionApiDiscoveryResult,
) -> None:
    if run_diagnostics is None:
        return
    run_diagnostics.auction_coverage = result.coverage
    run_diagnostics.live_auction_urls.clear()
    run_diagnostics.live_auction_urls.add(AUCTION_INDEX_URL)
    setattr(run_diagnostics, "auction_discovery_mode", PRIMARY_MODE)
    setattr(run_diagnostics, "auction_discovery_scope_status", result.scope_status)
    setattr(run_diagnostics, "auction_discovered_rows", result.rows_seen)
    setattr(run_diagnostics, "auction_timer_parsed", result.timers_parsed)
    setattr(run_diagnostics, "auction_timerless_eligible", result.timerless_eligible)
    setattr(run_diagnostics, "auction_api_total", result.api_total)
    setattr(run_diagnostics, "auction_fallback_used", False)


def _legacy_fallback(
    page,
    run_diagnostics: Optional[watcher.RunDiagnostics],
) -> list[watcher.Lot]:
    watcher.log(
        "Discovery auction API item-level non prouvée -> fallback legacy ventes live"
    )
    if run_diagnostics is not None:
        run_diagnostics.auction_coverage = watcher.CoverageAudit(
            "AUCTIONS", watcher.AUCTION_DISCOVERY_FILTERS
        )
        run_diagnostics.live_auction_urls.clear()

    sales = _ORIGINAL_COLLECT_LIVE_AUCTION_URLS(page, run_diagnostics)
    if run_diagnostics is not None:
        run_diagnostics.record_live_sales(sales)
        setattr(run_diagnostics, "auction_discovery_mode", FALLBACK_MODE)
        setattr(
            run_diagnostics,
            "auction_discovery_scope_status",
            FALLBACK_SCOPE_STATUS,
        )
        setattr(run_diagnostics, "auction_discovered_rows", 0)
        setattr(run_diagnostics, "auction_timer_parsed", 0)
        setattr(run_diagnostics, "auction_timerless_eligible", 0)
        setattr(run_diagnostics, "auction_api_total", None)
        setattr(run_diagnostics, "auction_fallback_used", True)

    watcher.log(f"Fallback legacy: {len(sales)} vente(s) live détectée(s)")
    lots: dict[str, watcher.Lot] = {}
    for sale in sales:
        try:
            for lot in _ORIGINAL_COLLECT_LOTS_FROM_LISTING(
                page, sale, "auction", run_diagnostics
            ):
                lots.setdefault(lot.url, lot)
        except Exception as error:
            watcher.log(f"Fallback legacy erreur {type(error).__name__}: {sale}")
            if run_diagnostics is not None:
                run_diagnostics.auction_coverage.record_page_failure(
                    f"legacy fallback sale exception: {type(error).__name__}"
                )
    return list(lots.values())


def patched_collect_live_auction_urls(
    page,
    run_diagnostics: Optional[watcher.RunDiagnostics] = None,
) -> list[str]:
    watcher.log(
        "Source auction primaire: API publique /on-sale-items "
        "sellingTypeGroup=AUCTION + sortType=ENDING_SOON"
    )
    # The unchanged V4 main loop expects a list of discovery sources. This one
    # sentinel routes the auction phase through the API collector below.
    return [AUCTION_INDEX_URL]


def patched_collect_lots_from_listing(
    page,
    url: str,
    source_type: str,
    run_diagnostics: Optional[watcher.RunDiagnostics] = None,
    **kwargs,
) -> list[watcher.Lot]:
    if source_type != "auction" or url != AUCTION_INDEX_URL:
        return _ORIGINAL_COLLECT_LOTS_FROM_LISTING(
            page, url, source_type, run_diagnostics, **kwargs
        )

    result = discover_auction_api_lots()
    if result.complete:
        _attach_primary_result(run_diagnostics, result)
        watcher.log(
            f"Auction API item-level: {result.rows_seen} lot(s) reçu(s), "
            f"{result.timers_parsed} endTime lisible(s), "
            f"{len(result.lots)} candidat(s) Pokémon/carte/0-100 € dans l'horizon"
        )
        watcher.log(f"Auction scope status: {PRIMARY_SCOPE_STATUS}")
        return result.lots

    watcher.log(f"Auction API item-level incomplet: {result.reason}")
    return _legacy_fallback(page, run_diagnostics)


def patched_coverage_status(coverage: watcher.CoverageAudit) -> str:
    if (
        coverage.protocol == PRIMARY_PROTOCOL
        and getattr(coverage, "_auction_scope_complete", False)
    ):
        if coverage.incomplete_reasons or coverage.pages_failed:
            return watcher.COVERAGE_INCOMPLETE
        return watcher.COVERAGE_COMPLETE
    return _ORIGINAL_COVERAGE_STATUS_GETTER(coverage)


def patched_log_scan_coverage(diagnostics: watcher.RunDiagnostics) -> None:
    _ORIGINAL_LOG_SCAN_COVERAGE(diagnostics)
    mode = getattr(diagnostics, "auction_discovery_mode", "UNKNOWN")
    scope = getattr(diagnostics, "auction_discovery_scope_status", "UNKNOWN")
    rows = getattr(diagnostics, "auction_discovered_rows", 0)
    timer_parsed = getattr(diagnostics, "auction_timer_parsed", 0)
    timerless = getattr(diagnostics, "auction_timerless_eligible", 0)
    api_total = getattr(diagnostics, "auction_api_total", None)
    fallback = bool(getattr(diagnostics, "auction_fallback_used", False))

    watcher.log(f"auction discovery mode: {mode}")
    watcher.log(f"auction discovery scope status: {scope}")
    watcher.log(f"auction discovered rows: {rows}")
    watcher.log(f"auction timers parsed: {timer_parsed}")
    watcher.log(f"auction timerless eligible: {timerless}")
    watcher.log(
        f"auction API total (wider on-sale auction universe): "
        f"{api_total if api_total is not None else 'UNKNOWN'}"
    )
    watcher.log(f"auction legacy fallback used: {str(fallback).lower()}")

    watcher.write_github_output("auction_discovery_mode", mode)
    watcher.write_github_output("auction_scope_status", scope)
    watcher.write_github_output("auction_discovered_rows", rows)
    watcher.write_github_output("auction_timer_parsed", timer_parsed)
    watcher.write_github_output(
        "auction_ending_soon", diagnostics.auction_candidates_ending_soon
    )
    watcher.write_github_output("auction_fallback_used", str(fallback).lower())


def install_v4_auction_item_discovery() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    watcher.collect_live_auction_urls = patched_collect_live_auction_urls
    watcher.collect_lots_from_listing = patched_collect_lots_from_listing
    watcher.CoverageAudit.status = property(patched_coverage_status)
    watcher.log_scan_coverage = patched_log_scan_coverage
    _INSTALLED = True
