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
    if not identity_proven:
        # Preserve the observation but make it non-actionable downstream.
        identity = CommercialIdentity(
            identity.name,
            identity.set_name,
            identity.number,
            identity.language,
            identity.grader,
            identity.grade,
            identity.edition,
            identity.finish,
            identity.variant,
        )
    row = verified_fixed_ask(
        market="fanatics",
        identity=identity,
        price=price_usd,
        currency="USD",
        observed_at=observed_at,
        source_id=source_id,
        buyer_fee_rate=buyer_fee_rate,
        buyer_fee_flat=buyer_fee_flat_usd,
        logistics_cost=logistics_usd,
        note=note,
    )
    if identity_proven:
        return row
    return PriceObservation(
        source=row.source,
        identity=row.identity,
        evidence_type=row.evidence_type,
        price=row.price,
        currency=row.currency,
        observed_at=row.observed_at,
        identity_proven=False,
        buyer_fee_rate=row.buyer_fee_rate,
        buyer_fee_flat=row.buyer_fee_flat,
        logistics_cost=row.logistics_cost,
        note=row.note,
        source_id=row.source_id,
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
    row = verified_auction_snapshot(
        market="fanatics",
        identity=identity,
        price=price_usd,
        currency="USD",
        observed_at=observed_at,
        end_at=end_at,
        within_five_minutes=within_five_minutes,
        source_id=source_id,
        buyer_fee_rate=buyer_fee_rate,
        buyer_fee_flat=buyer_fee_flat_usd,
        logistics_cost=logistics_usd,
        note=note,
    )
    if identity_proven:
        return row
    return PriceObservation(
        source=row.source,
        identity=row.identity,
        evidence_type=row.evidence_type,
        price=row.price,
        currency=row.currency,
        observed_at=row.observed_at,
        identity_proven=False,
        end_at=row.end_at,
        buyer_fee_rate=row.buyer_fee_rate,
        buyer_fee_flat=row.buyer_fee_flat,
        logistics_cost=row.logistics_cost,
        note=row.note,
        source_id=row.source_id,
    )
