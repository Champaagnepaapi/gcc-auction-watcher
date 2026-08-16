from __future__ import annotations

import os
from math import ceil
from pathlib import Path
from time import monotonic
from typing import Callable, Optional

import watcher
from playwright.sync_api import sync_playwright

import v4_auction_item_discovery as item_discovery
from v4_auction_pagination_stability import discover_auction_api_lots_stable
from v4_private_auction_coverage import (
    AUGMENTED_FALLBACK_MODE,
    AUGMENTED_MODE,
    PrivateAuctionAugmentResult,
    _merge_by_url,
    discover_private_auction_lots,
)


LEGACY_TIMER_INSPECTION_ATTEMPTS = 2
LEGACY_TIMER_RETRY_WAIT_MS = 300


def write_output(name: str, value: object) -> None:
    output_path = os.getenv("GITHUB_OUTPUT", "").strip()
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def collect_legacy(
    page, horizon: int
) -> tuple[list[watcher.Lot], dict[str, str], watcher.RunDiagnostics]:
    diagnostics = watcher.RunDiagnostics()
    previous_horizon = watcher.MAX_AUCTION_MINUTES
    watcher.MAX_AUCTION_MINUTES = horizon
    try:
        sales = item_discovery._ORIGINAL_COLLECT_LIVE_AUCTION_URLS(page, diagnostics)
        lots: dict[str, watcher.Lot] = {}
        source_by_url: dict[str, str] = {}
        for sale in sales:
            try:
                for lot in item_discovery._ORIGINAL_COLLECT_LOTS_FROM_LISTING(
                    page, sale, "auction", diagnostics
                ):
                    if lot.url not in lots:
                        lots[lot.url] = lot
                        source_by_url[lot.url] = sale
            except Exception as error:
                diagnostics.auction_coverage.record_page_failure(
                    f"legacy comparison sale exception: {type(error).__name__}"
                )
        return list(lots.values()), source_by_url, diagnostics
    finally:
        watcher.MAX_AUCTION_MINUTES = previous_horizon


def collect_full_legacy_fallback(
    page, horizon: int
) -> tuple[list[watcher.Lot], watcher.RunDiagnostics]:
    """Execute the same full legacy fallback used by V4 production."""

    diagnostics = watcher.RunDiagnostics()
    previous_horizon = watcher.MAX_AUCTION_MINUTES
    watcher.MAX_AUCTION_MINUTES = horizon
    try:
        lots = item_discovery._legacy_fallback(page, diagnostics)
        return lots, diagnostics
    finally:
        watcher.MAX_AUCTION_MINUTES = previous_horizon


def resolve_legacy_ids(
    page,
    lots: list[watcher.Lot],
    horizon: int,
    *,
    inspection_attempts: int = LEGACY_TIMER_INSPECTION_ATTEMPTS,
    inspect_func: Optional[Callable] = None,
) -> tuple[set[str], set[str]]:
    """Resolve legacy candidates with one bounded retry for transient timer reads.

    This is validation-only. A timer that remains unreadable after the bounded
    retry is still unresolved and keeps the comparison red; no candidate is
    silently dropped or assumed to be outside the horizon.
    """

    if inspection_attempts < 1:
        raise ValueError("inspection_attempts must be >= 1")

    inspector = inspect_func or watcher.inspect_item
    resolved: set[str] = set()
    unresolved: set[str] = set()
    for lot in lots:
        current = lot
        if current.minutes_to_end is None or current.inspection_error:
            for attempt in range(inspection_attempts):
                try:
                    current = inspector(page, current)
                except Exception:
                    # Keep the previous state and retry once. A second failure
                    # remains unresolved and fails the live validation below.
                    pass

                if not current.inspection_error and current.minutes_to_end is not None:
                    break

                if attempt + 1 < inspection_attempts:
                    try:
                        page.wait_for_timeout(LEGACY_TIMER_RETRY_WAIT_MS)
                    except Exception:
                        pass

        if current.inspection_error or current.minutes_to_end is None:
            unresolved.add(lot.url)
            continue
        if current.current_price is None:
            continue
        if not (watcher.MIN_PRICE <= current.current_price <= watcher.MAX_PRICE):
            continue
        if current.minutes_to_end <= horizon:
            resolved.add(current.url)
    return resolved, unresolved


def _empty_supplemental_result() -> PrivateAuctionAugmentResult:
    return PrivateAuctionAugmentResult([], 0, 0, 0, 0)


def main() -> int:
    horizon = max(60, int(os.getenv("V4_AUCTION_COMPARE_MINUTES", "720")))
    print("=== V4 AUCTION DISCOVERY COMPARISON ===", flush=True)
    print(f"comparison horizon: {horizon} min (diagnostic only)", flush=True)
    print("economic/notification actions: 0", flush=True)

    api_result = discover_auction_api_lots_stable(max_minutes=horizon)
    api_snapshot_finished = monotonic()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="fr-FR", timezone_id="Europe/Zurich")
        effective_page = context.new_page()
        effective_page.set_default_timeout(watcher.TEXT_TIMEOUT)
        effective_page.set_default_navigation_timeout(watcher.NAV_TIMEOUT)
        comparison_page = context.new_page()
        comparison_page.set_default_timeout(watcher.TEXT_TIMEOUT)
        comparison_page.set_default_navigation_timeout(watcher.NAV_TIMEOUT)

        fallback_diagnostics = None
        if api_result.complete:
            effective_anchor = api_snapshot_finished
            base_lots = list(api_result.lots)
            effective_mode = AUGMENTED_MODE
        else:
            # This is the actual fail-closed V4 production behavior: when the
            # public API cannot prove valid ordering/completeness, use the full
            # legacy live-sale discovery rather than trusting partial API rows.
            effective_anchor = monotonic()
            base_lots, fallback_diagnostics = collect_full_legacy_fallback(
                effective_page, horizon
            )
            effective_mode = AUGMENTED_FALLBACK_MODE

        try:
            supplemental_result = discover_private_auction_lots(
                effective_page,
                run_diagnostics=fallback_diagnostics,
                max_minutes=horizon,
            )
        except Exception as error:
            print(
                "FAIL: supplemental private/weekly safety net raised "
                f"{type(error).__name__}",
                flush=True,
            )
            browser.close()
            return 1

        effective_lots, supplemental_added = _merge_by_url(
            base_lots, supplemental_result.lots
        )
        effective_ids = {
            lot.url
            for lot in effective_lots
            if lot.minutes_to_end is not None and lot.minutes_to_end <= horizon
        }

        legacy_lots, legacy_source_by_url, legacy_diagnostics = collect_legacy(
            comparison_page, horizon
        )

        # Restrict the later independent legacy sample to cards that were
        # certainly already inside H when the effective production path began.
        # This removes false misses caused only by countdown time passing.
        elapsed_seconds = max(0.0, monotonic() - effective_anchor)
        boundary_margin_minutes = max(1, ceil(elapsed_seconds / 60.0))
        legacy_comparable_horizon = max(0, horizon - boundary_margin_minutes)
        legacy_ids, legacy_unresolved = resolve_legacy_ids(
            comparison_page, legacy_lots, legacy_comparable_horizon
        )
        browser.close()

    effective_only = sorted(effective_ids.difference(legacy_ids))
    legacy_only = sorted(legacy_ids.difference(effective_ids))
    fallback_failures = (
        fallback_diagnostics.auction_coverage.pages_failed
        if fallback_diagnostics is not None
        else 0
    )
    legacy_failures = legacy_diagnostics.auction_coverage.pages_failed

    print(f"API primary complete: {str(api_result.complete).lower()}", flush=True)
    print(f"API primary scope: {api_result.scope_status}", flush=True)
    print(f"API primary protocol: {api_result.coverage.protocol}", flush=True)
    print(f"API primary reason: {api_result.reason}", flush=True)
    print(f"API total: {api_result.api_total}", flush=True)
    print(f"API pages requested: {api_result.coverage.pages_requested}", flush=True)
    print(f"API rows seen: {api_result.rows_seen}", flush=True)
    print(f"API timers parsed: {api_result.timers_parsed}", flush=True)
    print(f"effective production mode: {effective_mode}", flush=True)
    print(f"full fallback page failures: {fallback_failures}", flush=True)
    print(
        "supplemental sales checked: "
        f"{supplemental_result.private_sales_seen} private + "
        f"{supplemental_result.weekly_sales_seen} weekly",
        flush=True,
    )
    print(f"supplemental candidates added: {supplemental_added}", flush=True)
    print(f"supplemental safety-net failures: {supplemental_result.failures}", flush=True)
    print(f"effective candidates <= {horizon} min: {len(effective_ids)}", flush=True)
    print(
        "legacy comparison horizon: "
        f"{legacy_comparable_horizon} min "
        f"(elapsed={elapsed_seconds:.1f}s, margin={boundary_margin_minutes}m)",
        flush=True,
    )
    print(
        f"legacy candidates <= {legacy_comparable_horizon} min: {len(legacy_ids)}",
        flush=True,
    )
    print(f"legacy comparison page failures: {legacy_failures}", flush=True)
    print(f"effective only: {len(effective_only)}", flush=True)
    print(f"legacy only: {len(legacy_only)}", flush=True)
    print(f"legacy unresolved timers: {len(legacy_unresolved)}", flush=True)
    for url in effective_only[:20]:
        print(f"EFFECTIVE_ONLY {url}", flush=True)
    for url in legacy_only[:20]:
        source = legacy_source_by_url.get(url, "UNKNOWN_LEGACY_SOURCE")
        print(f"LEGACY_ONLY {url} SOURCE {source}", flush=True)
    for url in sorted(legacy_unresolved)[:20]:
        source = legacy_source_by_url.get(url, "UNKNOWN_LEGACY_SOURCE")
        print(f"LEGACY_UNRESOLVED {url} SOURCE {source}", flush=True)

    write_output("primary_complete", str(api_result.complete).lower())
    write_output("primary_scope", api_result.scope_status)
    write_output("primary_rows_seen", api_result.rows_seen)
    write_output("effective_mode", effective_mode)
    write_output("primary_candidates", len(effective_ids))
    write_output("legacy_candidates", len(legacy_ids))
    write_output("primary_only", len(effective_only))
    write_output("legacy_only", len(legacy_only))
    write_output("primary_unresolved", 0)
    write_output("legacy_unresolved", len(legacy_unresolved))

    if api_result.complete and api_result.scope_status != item_discovery.PRIMARY_SCOPE_STATUS:
        print("FAIL: complete API result has unexpected scope status", flush=True)
        return 1
    if fallback_failures:
        print("FAIL: full legacy fallback had page failures", flush=True)
        return 1
    if supplemental_result.failures:
        print("FAIL: supplemental private/weekly safety net had failures", flush=True)
        return 1
    if legacy_failures:
        print("FAIL: independent legacy comparison had page failures", flush=True)
        return 1
    if legacy_unresolved:
        print(
            "FAIL: independent legacy comparison still has unresolved timer(s) "
            "after bounded retry",
            flush=True,
        )
        return 1
    if legacy_only:
        print(
            "FAIL: effective production discovery missed candidate(s) already "
            "inside the common-time legacy horizon",
            flush=True,
        )
        return 1

    if api_result.complete:
        print(
            "PASS: stabilized API + private/stable-weekly safety net is a "
            "superset of independent legacy at a common-time horizon",
            flush=True,
        )
    else:
        print(
            "PASS WITH FAIL-CLOSED FALLBACK: API was not trusted; full legacy "
            "+ stable weekly safety net covered the independent legacy sample",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
