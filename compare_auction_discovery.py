from __future__ import annotations

import os
from pathlib import Path

import watcher
from playwright.sync_api import sync_playwright

from v4_auction_item_discovery import (
    PRIMARY_SCOPE_STATUS,
    _ORIGINAL_COLLECT_LIVE_AUCTION_URLS,
    _ORIGINAL_COLLECT_LOTS_FROM_LISTING,
    discover_auction_index_lots,
)


def write_output(name: str, value: object) -> None:
    output_path = os.getenv("GITHUB_OUTPUT", "").strip()
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def resolve_ending_soon_ids(
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


def main() -> int:
    horizon = max(60, int(os.getenv("V4_AUCTION_COMPARE_MINUTES", "720")))
    print("=== V4 AUCTION DISCOVERY COMPARISON ===", flush=True)
    print(f"comparison horizon: {horizon} min (diagnostic only)", flush=True)
    print("economic/notification actions: 0", flush=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="fr-FR", timezone_id="Europe/Zurich")
        primary_page = context.new_page()
        primary_page.set_default_timeout(watcher.TEXT_TIMEOUT)
        primary_page.set_default_navigation_timeout(watcher.NAV_TIMEOUT)
        legacy_page = context.new_page()
        legacy_page.set_default_timeout(watcher.TEXT_TIMEOUT)
        legacy_page.set_default_navigation_timeout(watcher.NAV_TIMEOUT)

        primary_result = discover_auction_index_lots(
            primary_page,
            max_minutes=horizon,
        )
        legacy_lots = collect_legacy(legacy_page, horizon)

        primary_ids, primary_unresolved = resolve_ending_soon_ids(
            primary_page, primary_result.lots, horizon
        )
        legacy_ids, legacy_unresolved = resolve_ending_soon_ids(
            legacy_page, legacy_lots, horizon
        )
        browser.close()

    primary_only = sorted(primary_ids.difference(legacy_ids))
    legacy_only = sorted(legacy_ids.difference(primary_ids))

    print(f"primary complete: {str(primary_result.complete).lower()}", flush=True)
    print(f"primary scope: {primary_result.scope_status}", flush=True)
    print(f"primary rows seen: {primary_result.rows_seen}", flush=True)
    print(f"primary timers parsed: {primary_result.timers_parsed}", flush=True)
    print(f"primary candidates <= horizon: {len(primary_ids)}", flush=True)
    print(f"legacy candidates <= horizon: {len(legacy_ids)}", flush=True)
    print(f"primary only: {len(primary_only)}", flush=True)
    print(f"legacy only: {len(legacy_only)}", flush=True)
    print(f"primary unresolved timers: {len(primary_unresolved)}", flush=True)
    print(f"legacy unresolved timers: {len(legacy_unresolved)}", flush=True)
    for url in primary_only[:10]:
        print(f"PRIMARY_ONLY {url}", flush=True)
    for url in legacy_only[:10]:
        print(f"LEGACY_ONLY {url}", flush=True)

    write_output("primary_complete", str(primary_result.complete).lower())
    write_output("primary_scope", primary_result.scope_status)
    write_output("primary_rows_seen", primary_result.rows_seen)
    write_output("primary_candidates", len(primary_ids))
    write_output("legacy_candidates", len(legacy_ids))
    write_output("primary_only", len(primary_only))
    write_output("legacy_only", len(legacy_only))
    write_output("primary_unresolved", len(primary_unresolved))
    write_output("legacy_unresolved", len(legacy_unresolved))

    if not primary_result.complete:
        print(f"FAIL: primary discovery incomplete: {primary_result.reason}", flush=True)
        return 1
    if primary_result.scope_status != PRIMARY_SCOPE_STATUS:
        print("FAIL: unexpected primary scope status", flush=True)
        return 1
    if primary_unresolved:
        print("FAIL: primary left timerless candidate(s) unresolved", flush=True)
        return 1
    if legacy_only:
        print("FAIL: new discovery missed candidate(s) seen by legacy", flush=True)
        return 1

    print("PASS: item-level discovery is a superset of legacy for this run", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
