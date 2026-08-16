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

SUPPORTED_OFFER_MARKETS = frozenset({"gcc", "cardova", "magi", "fanatics", "comc"})


def verified_fixed_ask(
    *,
    market: str,
    identity: CommercialIdentity,
    price: float,
    currency: str,
    observed_at: datetime,
    source_id: str = "",
    buyer_fee_rate: Optional[float] = 0.0,
    buyer_fee_flat: float = 0.0,
    logistics_cost: float = 0.0,
    note: str = "",
) -> PriceObservation:
    source = market.strip().casefold()
    if source not in SUPPORTED_OFFER_MARKETS:
        raise ValueError(f"unsupported market: {market}")
    return PriceObservation(
        source=source,
        identity=identity,
        evidence_type=FIXED_ASK,
        price=price,
        currency=currency,
        observed_at=observed_at,
        identity_proven=identity.complete_for_exact_market and identity.opportunity_language,
        buyer_fee_rate=buyer_fee_rate,
        buyer_fee_flat=buyer_fee_flat,
        logistics_cost=logistics_cost,
        note=note,
        source_id=source_id,
    )


def verified_auction_snapshot(
    *,
    market: str,
    identity: CommercialIdentity,
    price: float,
    currency: str,
    observed_at: datetime,
    end_at: datetime,
    within_five_minutes: bool,
    source_id: str = "",
    buyer_fee_rate: Optional[float],
    buyer_fee_flat: float = 0.0,
    logistics_cost: float = 0.0,
    note: str = "",
) -> PriceObservation:
    source = market.strip().casefold()
    if source not in SUPPORTED_OFFER_MARKETS:
        raise ValueError(f"unsupported market: {market}")
    return PriceObservation(
        source=source,
        identity=identity,
        evidence_type=AUCTION_SNAPSHOT_LE5 if within_five_minutes else ACTIVE_AUCTION,
        price=price,
        currency=currency,
        observed_at=observed_at,
        identity_proven=identity.complete_for_exact_market and identity.opportunity_language,
        end_at=end_at,
        buyer_fee_rate=buyer_fee_rate,
        buyer_fee_flat=buyer_fee_flat,
        logistics_cost=logistics_cost,
        note=note,
        source_id=source_id,
    )
