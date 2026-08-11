from __future__ import annotations

import os
from math import ceil
from pathlib import Path
from time import monotonic

import watcher
from playwright.sync_api import sync_playwright

from v4_auction_item_discovery import (
    PRIMARY_SCOPE_STATUS,
    _ORIGINAL_COLLECT_LIVE_AUCTION_URLS,
    _ORIGINAL_COLLECT_LOTS_FROM_LISTING,
    discover_auction_api_lots,
)


def write_output(name: str, value: object) -> None:
    output_path = os.getenv("GITHUB_OUTPUT", "").strip()
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def collect_legacy(page, horizon: int) -> list[watcher.Lot]:
    diagnostics = watcher.RunDiagnostics()
    previous_horizon = watcher.MAX_AUCTION_MINUTES
    watcher.MAX_AUCTION_MINUTES = horizon
    try:
        sales = _ORIGINAL_COLLECT_LIVE_AUCTION_URLS(page, diagnostics)
        lots: dict[str, watcher.Lot] = {}
        for sale in sales:
            for lot in _ORIGINAL_COLLECT_LOTS_FROM_LISTING(
                page, sale, "auction", diagnostics
            ):
                lots.setdefault(lot.url, lot)
        return list(lots.values())
    finally:
        watcher.MAX_AUCTION_MINUTES = previous_horizon


def resolve_legacy_ids(
    page,
    lots: list[watcher.Lot],
    horizon: int,
) -> tuple[set[str], set[str]]:
    resolved: set[str] = set()
    unresolved: set[str] = set()
    for lot in lots:
        current = lot
        if current.minutes_to_end is None:
            try:
                current = watcher.inspect_item(page, current)
            except Exception:
                unresolved.add(lot.url)
                continue
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


def main() -> int:
    horizon = max(60, int(os.getenv("V4_AUCTION_COMPARE_MINUTES", "720")))
    print("=== V4 AUCTION DISCOVERY COMPARISON ===", flush=True)
    print(f"comparison horizon: {horizon} min (diagnostic only)", flush=True)
    print("economic/notification actions: 0", flush=True)

    primary_result = discover_auction_api_lots(max_minutes=horizon)
    primary_snapshot_finished = monotonic()
    primary_ids = {
        lot.url
        for lot in primary_result.lots
        if lot.minutes_to_end is not None and lot.minutes_to_end <= horizon
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="fr-FR", timezone_id="Europe/Zurich")
        legacy_page = context.new_page()
        legacy_page.set_default_timeout(watcher.TEXT_TIMEOUT)
        legacy_page.set_default_navigation_timeout(watcher.NAV_TIMEOUT)
        legacy_lots = collect_legacy(legacy_page, horizon)

        # The API snapshot is taken first, while the legacy collector needs tens
        # of seconds to open all sale pages. Comparing both at the same numeric
        # horizon therefore creates a deterministic boundary race: a lot can be
        # >H at the API snapshot and become <=H before legacy reads it. Restrict
        # the later legacy sample to a horizon that was certainly already inside
        # H at the earlier API snapshot. One full minute is always reserved to
        # account for integer countdown rounding.
        elapsed_seconds = max(0.0, monotonic() - primary_snapshot_finished)
        boundary_margin_minutes = max(1, ceil(elapsed_seconds / 60.0))
        legacy_comparable_horizon = max(0, horizon - boundary_margin_minutes)
        legacy_ids, legacy_unresolved = resolve_legacy_ids(
            legacy_page, legacy_lots, legacy_comparable_horizon
        )
        browser.close()

    primary_only = sorted(primary_ids.difference(legacy_ids))
    legacy_only = sorted(legacy_ids.difference(primary_ids))

    print(f"primary complete: {str(primary_result.complete).lower()}", flush=True)
    print(f"primary scope: {primary_result.scope_status}", flush=True)
    print(f"primary protocol: {primary_result.coverage.protocol}", flush=True)
    print(f"primary API total: {primary_result.api_total}", flush=True)
    print(f"primary pages requested: {primary_result.coverage.pages_requested}", flush=True)
    print(f"primary rows seen: {primary_result.rows_seen}", flush=True)
    print(f"primary timers parsed: {primary_result.timers_parsed}", flush=True)
    print(f"primary threshold crossed: {str(primary_result.threshold_crossed).lower()}", flush=True)
    print(f"primary candidates <= {horizon} min: {len(primary_ids)}", flush=True)
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
    print(f"primary only: {len(primary_only)}", flush=True)
    print(f"legacy only: {len(legacy_only)}", flush=True)
    print(f"legacy unresolved timers: {len(legacy_unresolved)}", flush=True)
    for url in primary_only[:20]:
        print(f"PRIMARY_ONLY {url}", flush=True)
    for url in legacy_only[:20]:
        print(f"LEGACY_ONLY {url}", flush=True)

    write_output("primary_complete", str(primary_result.complete).lower())
    write_output("primary_scope", primary_result.scope_status)
    write_output("primary_rows_seen", primary_result.rows_seen)
    write_output("primary_candidates", len(primary_ids))
    write_output("legacy_candidates", len(legacy_ids))
    write_output("primary_only", len(primary_only))
    write_output("legacy_only", len(legacy_only))
    write_output("primary_unresolved", 0)
    write_output("legacy_unresolved", len(legacy_unresolved))

    if not primary_result.complete:
        print(f"FAIL: primary discovery incomplete: {primary_result.reason}", flush=True)
        return 1
    if primary_result.scope_status != PRIMARY_SCOPE_STATUS:
        print("FAIL: unexpected primary scope status", flush=True)
        return 1
    if legacy_only:
        print("FAIL: API discovery missed candidate(s) already inside the common-time legacy horizon", flush=True)
        return 1

    print("PASS: API item-level discovery is a superset of legacy at a common-time horizon", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
