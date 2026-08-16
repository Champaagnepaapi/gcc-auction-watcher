from __future__ import annotations

from datetime import timedelta
from typing import Any, Mapping, Optional

from v4_global_market_core import (
    EBAY_GRADED_AGGREGATE,
    AggregatedSoldEvidence,
    CommercialIdentity,
    _as_utc,
)


def _positive(value: object) -> Optional[float]:
    try:
        number = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and number > 0 else None


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def ppt_metrics_to_aggregate(
    identity: CommercialIdentity,
    metrics: Mapping[str, Any],
    *,
    observed_at,
    identity_proven: bool,
    source: str = "ppt",
) -> Optional[AggregatedSoldEvidence]:
    """Normalize already-validated PPT metrics; this function performs no network calls.

    PPT remains SOLD_AGGREGATED. It is never converted into an item-level SOLD.
    The caller must explicitly prove the exact physical identity before using it.
    """
    if not identity_proven or not identity.complete_for_exact_market or not identity.opportunity_language:
        return None
    evidence_class = str(metrics.get("evidence_class") or "SOLD_AGGREGATED").strip().upper()
    if evidence_class != "SOLD_AGGREGATED":
        return None
    central = _positive(metrics.get("fair_value_eur"))
    count = _nonnegative_int(metrics.get("sales_count"))
    if central is None or count <= 0:
        return None
    observed = _as_utc(observed_at)
    age = _nonnegative_int(metrics.get("last_sale_age_days"))
    last_sale_at = observed - timedelta(days=age) if metrics.get("last_sale_age_days") is not None else None
    low = _positive(metrics.get("recent_level_30d_eur"))
    high = _positive(metrics.get("recent_level_90d_eur"))
    if low is None:
        low = central
    if high is None:
        high = central
    low, high = min(low, central, high), max(low, central, high)
    return AggregatedSoldEvidence(
        source=source,
        identity=identity,
        central=central,
        low=low,
        high=high,
        currency="EUR",
        observed_at=observed,
        identity_proven=True,
        sale_count=count,
        last_sale_at=last_sale_at,
        recent_90_count=_nonnegative_int(metrics.get("sales_90d") or metrics.get("recent_90_count")),
        correlation_family=EBAY_GRADED_AGGREGATE,
        note="PokemonPriceTracker graded eBay SOLD_AGGREGATED; not item-level SOLD",
    )
