from __future__ import annotations

from datetime import datetime
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


def _count(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def poketrace_estimate_to_aggregate(
    identity: CommercialIdentity,
    estimate: Mapping[str, Any],
    *,
    observed_at: datetime,
    identity_proven: bool,
    last_sale_at: Optional[datetime] = None,
    source: str = "poketrace",
) -> Optional[AggregatedSoldEvidence]:
    """Normalize a strict PokeTrace graded aggregate into the common evidence model.

    PokeTrace and PPT share the eBay graded aggregate correlation family. If
    PokeTrace does not prove a last-sale timestamp, the evidence remains useful
    context but cannot establish a recent fair value by itself.
    """
    if not identity_proven or not identity.complete_for_exact_market or not identity.opportunity_language:
        return None
    central = _positive(estimate.get("central") or estimate.get("central_eur"))
    low = _positive(estimate.get("low") or estimate.get("low_eur"))
    high = _positive(estimate.get("high") or estimate.get("high_eur"))
    count = _count(estimate.get("exact_grade_count") or estimate.get("sale_count"))
    if central is None or count <= 0:
        return None
    observed = _as_utc(observed_at)
    last = _as_utc(last_sale_at) if last_sale_at is not None else None
    return AggregatedSoldEvidence(
        source=source,
        identity=identity,
        central=central,
        low=min(low or central, central),
        high=max(high or central, central),
        currency="EUR",
        observed_at=observed,
        identity_proven=True,
        sale_count=count,
        last_sale_at=last,
        recent_90_count=_count(estimate.get("recent_90_count")),
        correlation_family=EBAY_GRADED_AGGREGATE,
        note="PokeTrace graded eBay aggregate; correlated with PPT; not item-level SOLD",
    )
