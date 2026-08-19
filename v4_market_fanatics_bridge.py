from __future__ import annotations

from datetime import datetime
from typing import Optional

from v4_global_market_core import CommercialIdentity, PriceObservation
from v4_market_verified_offer import verified_auction_snapshot, verified_fixed_ask


def fanatics_fixed_offer(
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
    return verified_fixed_ask(
        market="fanatics",
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


def fanatics_auction_offer(
    *,
    identity: CommercialIdentity,
    price_usd: float,
    observed_at: datetime,
    end_at: datetime,
    source_id: str,
    identity_proven: bool,
    within_five_minutes: bool,
    buyer_fee_rate: Optional[float],
    buyer_fee_flat_usd: float = 0.0,
    logistics_usd: float = 0.0,
    note: str = "",
) -> PriceObservation:
    return verified_auction_snapshot(
        market="fanatics",
        identity=identity,
        price=price_usd,
        currency="USD",
        observed_at=observed_at,
        end_at=end_at,
        within_five_minutes=within_five_minutes,
        identity_proven=identity_proven,
        source_id=source_id,
        buyer_fee_rate=buyer_fee_rate,
        buyer_fee_flat=buyer_fee_flat_usd,
        logistics_cost=logistics_usd,
        note=note,
    )
