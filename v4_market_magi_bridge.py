from __future__ import annotations

from datetime import datetime
from typing import Optional

from v4_global_market_core import FIXED_ASK, CommercialIdentity, PriceObservation


def magi_fixed_ask_to_observation(
    *,
    identity: CommercialIdentity,
    price_jpy: float,
    observed_at: datetime,
    source_id: str,
    identity_proven: bool,
    buyer_fee_rate: Optional[float],
    buyer_fee_flat_jpy: float = 0.0,
    logistics_jpy: float = 0.0,
    note: str = "",
) -> PriceObservation:
    """Normalize a magi individual fixed ask after strict identity proof.

    This bridge does not scrape and does not relax the existing Japan Edge
    identity gate. Unknown buyer economics remain None and fail closed.
    """
    return PriceObservation(
        source="magi",
        identity=identity,
        evidence_type=FIXED_ASK,
        price=price_jpy,
        currency="JPY",
        observed_at=observed_at,
        identity_proven=bool(identity_proven and identity.complete_for_exact_market and identity.opportunity_language),
        buyer_fee_rate=buyer_fee_rate,
        buyer_fee_flat=buyer_fee_flat_jpy,
        logistics_cost=logistics_jpy,
        note=note,
        source_id=source_id,
    )
