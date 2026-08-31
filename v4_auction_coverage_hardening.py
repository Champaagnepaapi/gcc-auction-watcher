from __future__ import annotations

from dataclasses import replace
from typing import Optional

import watcher
import v4_auction_item_discovery as item_discovery


# Recovery-only horizon. Normal production keeps the canonical fast path and
# stops as soon as the verified ENDING_SOON order crosses the requested horizon.
# We use this unreachable horizon only after GCC has already proven that its
# advertised order is locally inconsistent for the current snapshot.
_EXHAUSTIVE_HORIZON_MINUTES = 1_000_000_000
_ORDER_DRIFT_REASON = "auction API ending-soon order invalid"
_ORIGINAL_DISCOVER_AUCTION_API_LOTS = item_discovery.discover_auction_api_lots
_ORIGINAL_ORDER_VALIDATOR = item_discovery._api_order_is_valid
_ORIGINAL_MAYBE_NOTIFY_INCOMPLETE_COVERAGE = watcher.maybe_notify_incomplete_coverage
_INSTALLED = False
_ALERT_CLARITY_INSTALLED = False


def discover_auction_api_lots_exhaustive(
    *,
    max_minutes: Optional[int] = None,
    http_get=None,
    page_size: int = item_discovery.AUCTION_API_PAGE_SIZE,
    max_pages: int = item_discovery.AUCTION_API_MAX_PAGES,
    now=None,
) -> item_discovery.AuctionApiDiscoveryResult:
    """Recovery proof used only when GCC's ENDING_SOON order has drifted.

    The filtered AUCTION + ON_SALE query is paginated until the API itself is
    exhausted. The requested production horizon is then applied locally to all
    parsed rows. Ordering is observed but is no longer used as a stop condition.

    Structural failures remain fail-closed in the canonical collector: request
    failures, malformed rows/endTime, repeated pages, no progress, invalid
    nextPage and the max-page safety bound still return incomplete and trigger
    the existing legacy fallback.
    """

    horizon = (
        watcher.MAX_AUCTION_MINUTES
        if max_minutes is None
        else max(0, int(max_minutes))
    )
    order_verified = True

    def permissive_order_tracker(previous, current) -> bool:
        nonlocal order_verified
        if not _ORIGINAL_ORDER_VALIDATOR(previous, current):
            order_verified = False
        # Ordering is not used as a completeness proof in recovery mode.
        return True

    previous_validator = item_discovery._api_order_is_valid
    item_discovery._api_order_is_valid = permissive_order_tracker
    try:
        result = _ORIGINAL_DISCOVER_AUCTION_API_LOTS(
            max_minutes=_EXHAUSTIVE_HORIZON_MINUTES,
            http_get=http_get,
            page_size=page_size,
            max_pages=max_pages,
            now=now,
        )
    finally:
        item_discovery._api_order_is_valid = previous_validator

    # Every structural failure produced by the canonical collector stays
    # authoritative and fail-closed.
    if not result.complete:
        return replace(result, order_verified=False)

    # A successful recovery proof must end because the API itself is exhausted.
    # Anything else is unexpected and must not synthesize success.
    if result.reason != item_discovery.PRIMARY_EXHAUSTED_REASON:
        result.coverage.mark_incomplete(
            "auction exhaustive recovery did not reach API exhaustion",
            watcher.END_NO_PROGRESS,
        )
        setattr(result.coverage, "_auction_scope_complete", False)
        setattr(
            result.coverage,
            "auction_scope_status",
            item_discovery.FALLBACK_SCOPE_STATUS,
        )
        return replace(
            result,
            lots=[],
            complete=False,
            scope_status=item_discovery.FALLBACK_SCOPE_STATUS,
            order_verified=False,
            reason="auction exhaustive recovery did not reach API exhaustion",
        )

    inside: list[watcher.Lot] = []
    outside_horizon = False
    for lot in result.lots:
        minutes = lot.minutes_to_end
        if minutes is None:
            result.coverage.mark_incomplete(
                "auction exhaustive recovery produced a timerless candidate",
                watcher.END_MALFORMED_RESPONSE,
            )
            setattr(result.coverage, "_auction_scope_complete", False)
            setattr(
                result.coverage,
                "auction_scope_status",
                item_discovery.FALLBACK_SCOPE_STATUS,
            )
            return replace(
                result,
                lots=[],
                complete=False,
                scope_status=item_discovery.FALLBACK_SCOPE_STATUS,
                order_verified=False,
                reason="auction exhaustive recovery produced timerless candidate",
            )
        if minutes <= horizon:
            inside.append(lot)
            continue

        outside_horizon = True
        result.coverage.record_terminal(
            lot.url,
            watcher.ACCOUNT_EXCLUDED_BY_RULES,
        )

    if not order_verified:
        watcher.log(
            "Auction API ENDING_SOON order drift observed; "
            "coverage recovered by exhaustive filtered pagination"
        )

    result.coverage.pagination_end_reason = item_discovery.PRIMARY_EXHAUSTED_REASON
    setattr(result.coverage, "_auction_scope_complete", True)
    setattr(
        result.coverage,
        "auction_scope_status",
        item_discovery.PRIMARY_SCOPE_STATUS,
    )
    return replace(
        result,
        lots=inside,
        complete=True,
        scope_status=item_discovery.PRIMARY_SCOPE_STATUS,
        order_verified=order_verified,
        threshold_crossed=outside_horizon,
        reason=item_discovery.PRIMARY_EXHAUSTED_REASON,
    )


def discover_auction_api_lots_hardened(
    *,
    max_minutes: Optional[int] = None,
    http_get=None,
    page_size: int = item_discovery.AUCTION_API_PAGE_SIZE,
    max_pages: int = item_discovery.AUCTION_API_MAX_PAGES,
    now=None,
) -> item_discovery.AuctionApiDiscoveryResult:
    """Keep the fast canonical path; recover only from proven order drift."""

    horizon = (
        watcher.MAX_AUCTION_MINUTES
        if max_minutes is None
        else max(0, int(max_minutes))
    )
    primary = _ORIGINAL_DISCOVER_AUCTION_API_LOTS(
        max_minutes=horizon,
        http_get=http_get,
        page_size=page_size,
        max_pages=max_pages,
        now=now,
    )
    if primary.complete or primary.reason != _ORDER_DRIFT_REASON:
        return primary

    watcher.log(
        "Auction API ENDING_SOON order drift -> bounded exhaustive recovery "
        "for this snapshot only"
    )
    recovered = discover_auction_api_lots_exhaustive(
        max_minutes=horizon,
        http_get=http_get,
        page_size=page_size,
        max_pages=max_pages,
        now=now,
    )
    if recovered.complete:
        watcher.log(
            "Auction API order-drift recovery complete: "
            f"{recovered.rows_seen} row(s), {len(recovered.lots)} candidate(s) "
            f"<= {horizon} min"
        )
    return recovered


def format_actionable_technical_coverage_message(
    diagnostics: watcher.RunDiagnostics,
) -> str:
    """Describe the real coverage blocker without conflating P4 with unseen cards."""

    fixed = diagnostics.fixed_coverage
    auction = diagnostics.auction_coverage
    fixed_economic = diagnostics.fixed_economic_coverage
    auction_economic = diagnostics.auction_economic_coverage
    queue = diagnostics.fixed_queue
    scope_status = getattr(
        diagnostics,
        "auction_discovery_scope_status",
        getattr(auction, "auction_scope_status", "UNKNOWN"),
    )
    trustworthy = "YES" if diagnostics.economic_result_trustworthy else "NO"

    return (
        "GCC SCAN COVERAGE — ACTION REQUIRED\n"
        f"Discovery fixed universe: {fixed.unique_listings}/"
        f"{fixed.expected_total if fixed.expected_total is not None else 'UNKNOWN'}"
        f" | {fixed.status}\n"
        f"Discovery auctions target scope: {auction.unique_listings} listing(s) observed"
        f" | {auction.status} | {scope_status}\n"
        f"Fixed first-evaluation: {queue.first_evaluation_coverage_status}"
        f" | backlog {queue.first_evaluation_backlog}"
        f" | attempted this run {fixed_economic.attempted}\n"
        f"Fixed external-market proof: {queue.external_market_coverage_status}"
        f" | pending retry {queue.external_pending_backlog}"
        f" | fresh already evaluated {queue.fresh_already_evaluated}\n"
        f"Auction economic <=60m: {auction_economic.attempted}/"
        f"{auction_economic.candidates} attempted | {auction_economic.status}"
        f" | deferred by economic cap {auction_economic.skipped_by_cap}\n"
        f"Urgent fixed deferred: new "
        f"{queue.budget_skipped_count(watcher.QUEUE_P0_NEW)} | changed "
        f"{queue.budget_skipped_count(watcher.QUEUE_P1_CHANGED)}\n"
        f"Never-evaluated fixed backlog: "
        f"{queue.backlog_count(watcher.QUEUE_P2_NEVER_EVALUATED)}\n"
        f"State issue: {diagnostics.state_issue or 'NONE'}\n"
        f"DISCOVERY OVERALL: {diagnostics.discovery_coverage_status}\n"
        f"ECONOMIC OVERALL: {diagnostics.economic_coverage_status}\n"
        f"GLOBAL COVERAGE: {diagnostics.scan_coverage_status}\n"
        f"ECONOMIC RESULT TRUSTWORTHY: {trustworthy}\n"
        "Discovery itself is not capped by valuation/provider budgets."
    )


def guarded_maybe_notify_incomplete_coverage(
    diagnostics: watcher.RunDiagnostics,
    state: dict,
    now,
) -> bool:
    """Preserve canonical dedupe/cooldown and replace only the alert body."""

    original_post = watcher.requests.post
    message = format_actionable_technical_coverage_message(diagnostics)

    def clarity_post(url, *args, **kwargs):
        headers = kwargs.get("headers") or {}
        if headers.get("Title") == "GCC SCAN INCOMPLETE":
            kwargs["data"] = message.encode("utf-8")
        return original_post(url, *args, **kwargs)

    watcher.requests.post = clarity_post
    try:
        return _ORIGINAL_MAYBE_NOTIFY_INCOMPLETE_COVERAGE(
            diagnostics,
            state,
            now,
        )
    finally:
        watcher.requests.post = original_post


def install_v4_auction_coverage_hardening() -> None:
    """Install order-drift recovery plus truthful technical-alert wording."""

    global _INSTALLED
    global _ALERT_CLARITY_INSTALLED
    if not _INSTALLED:
        item_discovery.discover_auction_api_lots = discover_auction_api_lots_hardened
        _INSTALLED = True
    if not _ALERT_CLARITY_INSTALLED:
        watcher.maybe_notify_incomplete_coverage = guarded_maybe_notify_incomplete_coverage
        _ALERT_CLARITY_INSTALLED = True
