from __future__ import annotations

from datetime import datetime
from typing import Optional

from v4_global_market_core import (
    ACTIVE_AUCTION,
    AUCTION_SNAPSHOT_LE5,
    FIXED_ASK,
    CommercialIdentity,
    PriceObservation,
)


def gcc_offer_to_observation(
    *,
    identity: CommercialIdentity,
    price_eur: float,
    observed_at: datetime,
    source_id: str,
    offer_type: str,
    identity_proven: bool,
    buyer_fee_rate: Optional[float],
    buyer_fee_flat_eur: float = 0.0,
    logistics_eur: float = 0.0,
    end_at: Optional[datetime] = None,
    within_five_minutes: bool = False,
    note: str = "",
) -> PriceObservation:
    """Bridge an already-canonical GCC offer into the global competition layer.

    Fee policy is deliberately caller-supplied. Unknown buyer fees remain None
    and therefore fail closed for exact all-in ranking.
    """
    normalized = offer_type.strip().casefold()
    if normalized == "fixed":
        evidence_type = FIXED_ASK
    elif normalized == "auction":
        evidence_type = AUCTION_SNAPSHOT_LE5 if within_five_minutes else ACTIVE_AUCTION
    else:
        raise ValueError(f"unsupported GCC offer_type: {offer_type}")
    return PriceObservation(
        source="gcc",
        identity=identity,
        evidence_type=evidence_type,
        price=price_eur,
        currency="EUR",
        observed_at=observed_at,
        identity_proven=bool(identity_proven and identity.complete_for_exact_market and identity.opportunity_language),
        end_at=end_at,
        buyer_fee_rate=buyer_fee_rate,
        buyer_fee_flat=buyer_fee_flat_eur,
        logistics_cost=logistics_eur,
        note=note,
        source_id=source_id,
    )
