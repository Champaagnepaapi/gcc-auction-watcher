from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import watcher
import v4_auction_item_discovery as item_discovery


PRIVATE_AUCTION_PATH = "/filtres/auction/private/"
AUGMENTED_MODE = "AUCTION_API_PLUS_PRIVATE_LEGACY"
_INSTALLED = False


@dataclass(frozen=True)
class PrivateAuctionAugmentResult:
    lots: list[watcher.Lot]
    sales_seen: int
    private_sales_seen: int
    failures: int


def discover_private_auction_lots(
    page,
    *,
    run_diagnostics: Optional[watcher.RunDiagnostics] = None,
    max_minutes: Optional[int] = None,
) -> PrivateAuctionAugmentResult:
    """Read only the private-sale pages that the generic auction API can omit.

    This reuses V4's pre-API legacy collectors and all their existing Pokemon,
    single-card, price and timer filters. It is deliberately an additive safety
    net rather than a second economic pipeline.
    """

    previous_horizon = watcher.MAX_AUCTION_MINUTES
    if max_minutes is not None:
        watcher.MAX_AUCTION_MINUTES = max(0, int(max_minutes))
    try:
        sales = item_discovery._ORIGINAL_COLLECT_LIVE_AUCTION_URLS(
            page, run_diagnostics
        )
        private_sales = [
            sale for sale in sales if PRIVATE_AUCTION_PATH in str(sale)
        ]
        lots: dict[str, watcher.Lot] = {}
        failures = 0
        for sale in private_sales:
            try:
                for lot in item_discovery._ORIGINAL_COLLECT_LOTS_FROM_LISTING(
                    page, sale, "auction", run_diagnostics
                ):
                    lots.setdefault(lot.url, lot)
            except Exception as error:
                failures += 1
                watcher.log(
                    f"Private auction safety-net error {type(error).__name__}: {sale}"
                )
                if run_diagnostics is not None:
                    run_diagnostics.auction_coverage.record_page_failure(
                        f"private auction safety-net exception: {type(error).__name__}"
                    )
        return PrivateAuctionAugmentResult(
            list(lots.values()), len(sales), len(private_sales), failures
        )
    finally:
        watcher.MAX_AUCTION_MINUTES = previous_horizon


def _merge_by_url(
    primary: list[watcher.Lot],
    private: list[watcher.Lot],
) -> tuple[list[watcher.Lot], int]:
    merged = {lot.url: lot for lot in primary}
    before = len(merged)
    for lot in private:
        merged.setdefault(lot.url, lot)
    return list(merged.values()), len(merged) - before


def install_v4_private_auction_coverage() -> None:
    """Augment a successful API discovery with live private-auction pages."""

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

        mode = getattr(run_diagnostics, "auction_discovery_mode", "") if run_diagnostics else ""
        if mode != item_discovery.PRIMARY_MODE:
            # API failure already switched to the complete legacy fallback.
            return primary

        try:
            private_result = discover_private_auction_lots(
                page, run_diagnostics=run_diagnostics
            )
        except Exception as error:
            watcher.log(
                "Private auction safety-net discovery failed: "
                f"{type(error).__name__}"
            )
            if run_diagnostics is not None:
                run_diagnostics.auction_coverage.record_page_failure(
                    f"private auction safety-net discovery failed: {type(error).__name__}"
                )
                setattr(run_diagnostics, "auction_discovery_mode", AUGMENTED_MODE)
                setattr(run_diagnostics, "auction_private_augment_failed", True)
            return primary

        merged, added = _merge_by_url(primary, private_result.lots)
        watcher.log(
            "Private auction safety-net: "
            f"{private_result.private_sales_seen} private sale(s) checked, "
            f"{added} candidate(s) added, {private_result.failures} failure(s)"
        )
        if run_diagnostics is not None:
            setattr(run_diagnostics, "auction_discovery_mode", AUGMENTED_MODE)
            setattr(
                run_diagnostics,
                "auction_private_sales_checked",
                private_result.private_sales_seen,
            )
            setattr(run_diagnostics, "auction_private_candidates_added", added)
            setattr(
                run_diagnostics,
                "auction_private_augment_failed",
                bool(private_result.failures),
            )
        return merged

    watcher.collect_lots_from_listing = collect_with_private_safety_net
    _INSTALLED = True
