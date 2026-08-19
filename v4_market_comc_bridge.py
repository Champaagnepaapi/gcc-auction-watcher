from __future__ import annotations

from datetime import datetime
from typing import Optional

from v4_global_market_core import CommercialIdentity, PriceObservation
from v4_market_verified_offer import verified_fixed_ask


def comc_fixed_offer(
    *,
    identity: CommercialIdentity,
    price_usd: float,
    observed_at: datetime,
    source_id: str,
    identity_proven: bool,
    buyer_fee_rate: Optional[float],
    buyer_fee_flat_usd: float = 0.0,
    logistics_usd: float = 0.0,
    note: str = "",
) -> PriceObservation:
    """Normalize an exact COMC fixed listing after source identity proof.

    Buyer/logistics economics are caller-supplied so an unknown fee structure
    cannot silently become a false all-in bargain.
    """
    return verified_fixed_ask(
        market="comc",
        identity=identity,
        price=price_usd,
        currency="USD",
        observed_at=observed_at,
        identity_proven=identity_proven,
        source_id=source_id,
        buyer_fee_rate=buyer_fee_rate,
        buyer_fee_flat=buyer_fee_flat_usd,
        logistics_cost=logistics_usd,
        note=note,
    )
