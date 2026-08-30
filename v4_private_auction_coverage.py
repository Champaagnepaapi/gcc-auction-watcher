from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import watcher
import v4_auction_item_discovery as item_discovery


PRIVATE_AUCTION_PATH = "/filtres/auction/private/"
WEEKLY_AUCTION_PATH = "/filtres/auction/weekly/"
SUPPLEMENTAL_AUCTION_PATHS = (PRIVATE_AUCTION_PATH, WEEKLY_AUCTION_PATH)
WEEKLY_STABILITY_MAX_PASSES = 5
WEEKLY_STABILITY_FAILURE = "weekly auction legacy snapshot did not stabilize"
AUGMENTED_MODE = "AUCTION_API_PLUS_LEGACY_SAFETY_NET"
AUGMENTED_FALLBACK_MODE = "LEGACY_LIVE_SALES_FALLBACK_PLUS_STABLE_WEEKLY"
_INSTALLED = False


@dataclass(frozen=True)
class PrivateAuctionAugmentResult:
    lots: list[watcher.Lot]
    sales_seen: int
    private_sales_seen: int
    weekly_sales_seen: int
    failures: int


def _collect_weekly_sale_stable(
    page,
    sale: str,
    diagnostics: watcher.RunDiagnostics,
    *,
    max_passes: int = WEEKLY_STABILITY_MAX_PASSES,
) -> tuple[list[watcher.Lot], bool]:
    """Union repeated weekly snapshots until one full reload adds no URL.

    GCC weekly sale pages use dynamic/infinite-scroll rendering. Live comparison
    repeatedly showed one card absent from an earlier load and present on a
    later load of the same weekly sale. Two identical-growth states are not
    required: after the initial snapshot, a later snapshot that adds no new URL
    proves the bounded union has stabilized. Continued growth through the final
    pass fails closed instead of silently claiming complete supplemental cover.
    """

    if max_passes < 2:
        raise ValueError("weekly stability requires at least 2 passes")

    union: dict[str, watcher.Lot] = {}
    for pass_number in range(1, max_passes + 1):
        snapshot = item_discovery._ORIGINAL_COLLECT_LOTS_FROM_LISTING(
            page, sale, "auction", diagnostics
        )
        before = len(union)
        for lot in snapshot:
            if lot.url:
                union.setdefault(lot.url, lot)
        added = len(union) - before

        if pass_number >= 2 and added == 0:
            if pass_number > 2:
                watcher.log(
                    "Auction weekly stability guard: union stable after "
                    f"{pass_number} pass(es), {len(union)} candidate(s) | {sale}"
                )
            return list(union.values()), True

        if pass_number >= 2:
            watcher.log(
                "Auction weekly stability guard: snapshot drift detected, "
                f"pass {pass_number} added {added} candidate(s) | {sale}"
            )

    watcher.log(
        "Auction weekly stability guard: bounded snapshots still growing -> "
        f"fail closed | {sale}"
    )
    return list(union.values()), False


def discover_private_auction_lots(
    page,
    *,
    run_diagnostics: Optional[watcher.RunDiagnostics] = None,
    max_minutes: Optional[int] = None,
) -> PrivateAuctionAugmentResult:
    """Read private + stabilized weekly sale pages omitted by one live snapshot.

    Private sales are a known API gap and use one legacy pass. Weekly sales are
    reloaded until their URL union stabilizes because GCC's dynamic infinite
    scroll can omit a row on one snapshot. The diagnostics object is isolated so
    supplemental page totals cannot corrupt the primary API coverage ledger.
    The same guard is also applied after the full legacy fallback, so an invalid
    public API cannot reintroduce the weekly one-row omission.
    """

    previous_horizon = watcher.MAX_AUCTION_MINUTES
    supplemental_diagnostics = watcher.RunDiagnostics()
    if max_minutes is not None:
        watcher.MAX_AUCTION_MINUTES = max(0, int(max_minutes))
    try:
        sales = item_discovery._ORIGINAL_COLLECT_LIVE_AUCTION_URLS(
            page, supplemental_diagnostics
        )
        supplemental_sales = [
            sale
            for sale in sales
            if any(path in str(sale) for path in SUPPLEMENTAL_AUCTION_PATHS)
        ]
        private_sales_seen = sum(
            1 for sale in supplemental_sales if PRIVATE_AUCTION_PATH in str(sale)
        )
        weekly_sales_seen = sum(
            1 for sale in supplemental_sales if WEEKLY_AUCTION_PATH in str(sale)
        )
        lots: dict[str, watcher.Lot] = {}
        explicit_failures = 0
        for sale in supplemental_sales:
            try:
                if WEEKLY_AUCTION_PATH in str(sale):
                    sale_lots, stable = _collect_weekly_sale_stable(
                        page, sale, supplemental_diagnostics
                    )
                    if not stable:
                        explicit_failures += 1
                        supplemental_diagnostics.auction_coverage.mark_incomplete(
                            f"{WEEKLY_STABILITY_FAILURE}: {sale}",
                            watcher.END_NO_PROGRESS,
                        )
                else:
                    sale_lots = item_discovery._ORIGINAL_COLLECT_LOTS_FROM_LISTING(
                        page, sale, "auction", supplemental_diagnostics
                    )
                for lot in sale_lots:
                    lots.setdefault(lot.url, lot)
            except Exception as error:
                explicit_failures += 1
                watcher.log(
                    "Auction legacy safety-net error "
                    f"{type(error).__name__}: {sale}"
                )

        recorded_failures = supplemental_diagnostics.auction_coverage.pages_failed
        failures = max(explicit_failures, recorded_failures)
        if failures and run_diagnostics is not None:
            run_diagnostics.auction_coverage.record_page_failure(
                f"auction legacy safety-net page failures: {failures}"
            )

        return PrivateAuctionAugmentResult(
            list(lots.values()),
            len(sales),
            private_sales_seen,
            weekly_sales_seen,
            failures,
        )
    finally:
        watcher.MAX_AUCTION_MINUTES = previous_horizon


def _merge_by_url(
    primary: list[watcher.Lot],
    supplemental: list[watcher.Lot],
) -> tuple[list[watcher.Lot], int]:
    merged = {lot.url: lot for lot in primary}
    before = len(merged)
    for lot in supplemental:
        merged.setdefault(lot.url, lot)
    return list(merged.values()), len(merged) - before


def _suppress_primary_api_observed(
    supplemental: list[watcher.Lot],
    observed_ids: set[str],
) -> tuple[list[watcher.Lot], int]:
    """Keep the legacy safety net additive to, never overriding, primary API rows.

    ``discover_auction_api_lots`` records every stable API row in the primary
    coverage ledger, including rows terminally excluded because their exact API
    ``endTime`` is outside the <=60 minute horizon.  A later weekly/private DOM
    snapshot can expose the same URL with a different rendered countdown.  That
    does not make it an API gap and must not reintroduce the row for a second,
    conflicting terminal outcome.  Genuine safety-net gaps are URLs absent from
    the primary API ledger and remain eligible for augmentation.
    """

    if not observed_ids:
        return list(supplemental), 0
    kept: list[watcher.Lot] = []
    suppressed = 0
    for lot in supplemental:
        if lot.url and lot.url in observed_ids:
            suppressed += 1
            continue
        kept.append(lot)
    return kept, suppressed


def _augmented_mode(base_mode: str) -> Optional[str]:
    if base_mode == item_discovery.PRIMARY_MODE:
        return AUGMENTED_MODE
    if base_mode == item_discovery.FALLBACK_MODE:
        return AUGMENTED_FALLBACK_MODE
    return None


def install_v4_private_auction_coverage() -> None:
    """Augment API and full legacy fallback with stable private/weekly coverage."""

    global _INSTALLED
    if _INSTALLED:
        return

    original_collect = watcher.collect_lots_from_listing

    def collect_with_private_safety_net(
        page,
        url: str,
        source_type: str,
        run_diagnostics: Optional[watcher.RunDiagnostics] = None,
        **kwargs,
    ) -> list[watcher.Lot]:
        primary = original_collect(page, url, source_type, run_diagnostics, **kwargs)
        if source_type != "auction" or url != item_discovery.AUCTION_INDEX_URL:
            return primary

        base_mode = (
            getattr(run_diagnostics, "auction_discovery_mode", "")
            if run_diagnostics
            else ""
        )
        effective_mode = _augmented_mode(base_mode)
        if effective_mode is None:
            return primary

        try:
            supplemental_result = discover_private_auction_lots(
                page, run_diagnostics=run_diagnostics
            )
        except Exception as error:
            watcher.log(
                "Auction legacy safety-net discovery failed: "
                f"{type(error).__name__}"
            )
            if run_diagnostics is not None:
                run_diagnostics.auction_coverage.record_page_failure(
                    "auction legacy safety-net discovery failed: "
                    f"{type(error).__name__}"
                )
                setattr(run_diagnostics, "auction_discovery_mode", effective_mode)
                setattr(run_diagnostics, "auction_private_augment_failed", True)
            return primary

        supplemental_lots = supplemental_result.lots
        already_observed_suppressed = 0
        if run_diagnostics is not None and base_mode == item_discovery.PRIMARY_MODE:
            supplemental_lots, already_observed_suppressed = _suppress_primary_api_observed(
                supplemental_lots,
                set(run_diagnostics.auction_coverage.listing_ids),
            )
        merged, added = _merge_by_url(primary, supplemental_lots)
        watcher.log(
            "Auction legacy safety-net: "
            f"{supplemental_result.private_sales_seen} private + "
            f"{supplemental_result.weekly_sales_seen} weekly sale(s) checked, "
            f"{added} candidate(s) added, "
            f"{already_observed_suppressed} API-observed duplicate(s) suppressed, "
            f"{supplemental_result.failures} failure(s)"
        )
        if run_diagnostics is not None:
            setattr(run_diagnostics, "auction_discovery_mode", effective_mode)
            setattr(
                run_diagnostics,
                "auction_private_sales_checked",
                supplemental_result.private_sales_seen,
            )
            setattr(
                run_diagnostics,
                "auction_weekly_sales_checked",
                supplemental_result.weekly_sales_seen,
            )
            setattr(run_diagnostics, "auction_private_candidates_added", added)
            setattr(
                run_diagnostics,
                "auction_private_already_observed_suppressed",
                already_observed_suppressed,
            )
            setattr(
                run_diagnostics,
                "auction_private_augment_failed",
                bool(supplemental_result.failures),
            )
        return merged

    watcher.collect_lots_from_listing = collect_with_private_safety_net
    _INSTALLED = True
