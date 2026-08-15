from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import watcher
import v4_canonical_multimarket as multimarket
import v4_price_discovery as price_discovery
from run_watcher_safe import fixed_discovery_requires_technical_alert


ILLIQUID_AUCTION_MAX_MINUTES = max(
    0, int(os.getenv("V4_ILLIQUID_AUCTION_MAX_MINUTES", "5"))
)
ILLIQUID_GCC_ONLY_MIN_UPSIDE_RATIO = max(
    1.0, float(os.getenv("V4_ILLIQUID_GCC_ONLY_MIN_UPSIDE_RATIO", "1.75"))
)
ILLIQUID_GCC_ONLY_MIN_ABSOLUTE_UPSIDE_EUR = max(
    0.0, float(os.getenv("V4_ILLIQUID_GCC_ONLY_MIN_ABSOLUTE_UPSIDE_EUR", "10"))
)

_BASE_COLLECT_PRICE_DISCOVERY_LEAD = None
_BASE_MANUAL_REVIEW_SHOULD_NOTIFY = None
_INSTALLED = False


def _stable_manual_review_key(lot: watcher.Lot) -> str:
    """Deduplicate by the actual GCC listing, not an enrichment-sensitive identity."""
    url = str(lot.url or "").strip().rstrip("/")
    if url:
        return f"gcc-listing:{url}"
    return f"fallback:{watcher.external_commercial_identity_key(lot)}"


def _manual_review_should_notify_with_legacy_migration(
    state: dict,
    lead: multimarket.ManualReviewLead,
    now: datetime,
) -> bool:
    """Migrate the previous commercial-identity dedupe record to the stable listing key."""
    root = state.get(multimarket.MANUAL_REVIEW_STATE_KEY)
    if (
        isinstance(root, dict)
        and root.get("schema_version") == multimarket.MANUAL_REVIEW_SCHEMA_VERSION
    ):
        entries = root.get("entries")
        if isinstance(entries, dict) and lead.identity_key not in entries:
            legacy_key = watcher.external_commercial_identity_key(lead.lot)
            previous = entries.get(legacy_key)
            if isinstance(previous, dict):
                entries[lead.identity_key] = dict(previous)
    base = _BASE_MANUAL_REVIEW_SHOULD_NOTIFY or multimarket._manual_review_should_notify
    if base is _manual_review_should_notify_with_legacy_migration:
        return False
    return base(state, lead, now)


def _is_auction(lot: watcher.Lot) -> bool:
    source_type = str(lot.source_type or "").strip().casefold()
    return source_type == "auction" or lot.minutes_to_end is not None


def _has_external_graded_sold_anchor(
    signal: price_discovery.PriceDiscoverySignal,
) -> bool:
    for anchor in signal.credible_adjacent_anchors:
        source = str(anchor.source or "").strip().casefold()
        price_type = str(anchor.price_type or "").strip().upper()
        if (
            source not in {"", "gcc", "raw_consensus"}
            and price_type == "SOLD"
            and bool(str(anchor.grader or "").strip())
        ):
            return True
    return False


def _gcc_sold_anchor_count(
    signal: price_discovery.PriceDiscoverySignal,
) -> int:
    return sum(
        str(anchor.source or "").strip().casefold() == "gcc"
        and str(anchor.price_type or "").strip().upper() == "SOLD"
        for anchor in signal.credible_adjacent_anchors
    )


def _illiquid_phone_worthy(lead: multimarket.ManualReviewLead) -> bool:
    signal = lead.discovery_signal
    if signal is None:
        return False
    if signal.category != price_discovery.CATEGORY_ILLIQUID_PRICE_DISCOVERY:
        return True

    lot = lead.lot
    if _is_auction(lot):
        minutes = lot.minutes_to_end
        if minutes is None or minutes > ILLIQUID_AUCTION_MAX_MINUTES:
            return False

    if _has_external_graded_sold_anchor(signal):
        return True

    current = float(lot.current_price or 0.0)
    absolute_upside = max(0.0, float(signal.credible_high_reference) - current)
    return (
        _gcc_sold_anchor_count(signal) >= 2
        and signal.asymmetric_upside_ratio >= ILLIQUID_GCC_ONLY_MIN_UPSIDE_RATIO
        and absolute_upside >= ILLIQUID_GCC_ONLY_MIN_ABSOLUTE_UPSIDE_EUR
    )


def _no_v4_raw_market_signal(
    lot: watcher.Lot,
    canonical: multimarket.CanonicalCard,
) -> None:
    """V4 values slabs: RAW Cardmarket/TCGplayer prices must not rescue graded alerts."""
    del lot, canonical
    return None


def _guarded_collect_price_discovery_lead(
    candidate: watcher.ValuationCandidate,
    canonical: multimarket.CanonicalCard,
    raw: Optional[multimarket.RawMarketSignal],
    poketrace: Optional[watcher.ExternalMarketEvidence] = None,
    fallback: Optional[watcher.ExternalMarketEvidence] = None,
    now: Optional[datetime] = None,
) -> Optional[multimarket.ManualReviewLead]:
    # Explicitly discard RAW for V4 graded economics, even if a caller supplies it.
    base = _BASE_COLLECT_PRICE_DISCOVERY_LEAD
    if base is None or base is _guarded_collect_price_discovery_lead:
        return None
    lead = base(
        candidate,
        canonical,
        None,
        poketrace,
        fallback,
        now=now,
    )
    if lead is None:
        return None
    if not _illiquid_phone_worthy(lead):
        watcher.log(
            "Manual review log-only: signal insuffisant pour ntfy "
            f"({getattr(lead.discovery_signal, 'category', 'RAW')}) | {lead.lot.url}"
        )
        return None
    return lead


def actionable_technical_alert_required(
    diagnostics: watcher.RunDiagnostics,
) -> bool:
    """Phone alert only for real discovery loss, urgent backlog, or broken accounting."""
    queue = diagnostics.fixed_queue
    fixed_economic = diagnostics.fixed_economic_coverage
    auction_economic = diagnostics.auction_economic_coverage

    return any(
        (
            fixed_discovery_requires_technical_alert(diagnostics),
            diagnostics.auction_coverage.status == watcher.COVERAGE_INCOMPLETE,
            queue.budget_skipped_count(watcher.QUEUE_P0_NEW) > 0,
            queue.budget_skipped_count(watcher.QUEUE_P1_CHANGED) > 0,
            bool(queue.failed_ids),
            bool(diagnostics.state_issue),
            queue.initialized and not queue.accounting_coherent,
            fixed_economic.missing_attempts > 0,
            bool(fixed_economic.failed_ids),
            fixed_economic.finalized
            and fixed_economic.registered
            and not fixed_economic.accounting_coherent,
            auction_economic.missing_attempts > 0,
            bool(auction_economic.failed_ids),
            auction_economic.finalized
            and auction_economic.registered
            and not auction_economic.accounting_coherent,
        )
    )


def install_v4_notification_signal_quality_guard() -> None:
    """Install production-only notification quality rules without changing valuation math."""
    global _BASE_COLLECT_PRICE_DISCOVERY_LEAD
    global _BASE_MANUAL_REVIEW_SHOULD_NOTIFY
    global _INSTALLED
    if _INSTALLED:
        return

    # Capture the already-installed safety wrapper so this guard layers on top
    # instead of bypassing canonical identity fail-closed behavior.
    _BASE_COLLECT_PRICE_DISCOVERY_LEAD = multimarket._collect_price_discovery_lead
    _BASE_MANUAL_REVIEW_SHOULD_NOTIFY = multimarket._manual_review_should_notify

    # Cardmarket/TCGplayer RAW remains available as library code, but is excluded
    # from the production V4 slab opportunity path.
    multimarket.raw_market_signal = _no_v4_raw_market_signal
    multimarket._collect_price_discovery_lead = _guarded_collect_price_discovery_lead

    # A stable listing URL prevents the same GCC listing from re-notifying merely
    # because enrichment changed an identity component between runs.
    multimarket._manual_review_key = _stable_manual_review_key
    multimarket._manual_review_should_notify = (
        _manual_review_should_notify_with_legacy_migration
    )

    # Supersede the broader technical guard: expected bounded economic queues are
    # diagnostic only; actual discovery loss and urgent P0/P1 backlog remain ntfy.
    watcher._technical_alert_required = actionable_technical_alert_required
    _INSTALLED = True
