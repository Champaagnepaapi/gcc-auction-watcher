from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional, Protocol, Sequence, Tuple

from ..models import CardIdentity


@dataclass(frozen=True)
class ActiveAskingStats:
    currency: str
    count: int
    median: Optional[Decimal]
    q1: Optional[Decimal]
    q3: Optional[Decimal]
    robust_minimum: Optional[Decimal]
    dispersion: Optional[Decimal]
    source: str = "eBay active asking prices"
    limitation: str = "Active asking prices are not completed-sale market values"

    @property
    def sufficient_for_economic_valuation(self) -> bool:
        return False


def active_asking_statistics(
    prices: Iterable[Decimal], currency: str
) -> ActiveAskingStats:
    """Calcule des statistiques en memoire sans conserver les annonces."""

    values = tuple(sorted(Decimal(value) for value in prices if Decimal(value) >= 0))
    if not values:
        return ActiveAskingStats(currency, 0, None, None, None, None, None)
    median = _percentile(values, Decimal("0.5"))
    q1 = _percentile(values, Decimal("0.25"))
    q3 = _percentile(values, Decimal("0.75"))
    iqr = q3 - q1
    lower_fence = q1 - Decimal("1.5") * iqr
    robust = min(value for value in values if value >= lower_fence)
    dispersion = iqr / median if median > 0 else None
    return ActiveAskingStats(
        currency=currency,
        count=len(values),
        median=median,
        q1=q1,
        q3=q3,
        robust_minimum=robust,
        dispersion=dispersion,
    )


def _percentile(values: Sequence[Decimal], percentile: Decimal) -> Decimal:
    if len(values) == 1:
        return values[0]
    position = Decimal(len(values) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - Decimal(lower)
    return values[lower] + (values[upper] - values[lower]) * fraction


@dataclass(frozen=True)
class SoldComparable:
    price: Decimal
    currency: str
    sold_at: Optional[str]
    condition: Optional[str]
    sale_type: Optional[str]


class SoldMarketProvider(Protocol):
    enabled: bool
    live_calls: int

    def sold_comparables_for(self, identity: CardIdentity) -> Tuple[SoldComparable, ...]:
        ...


class MarketplaceInsightsProvider:
    """Interface reservee a une future source eBay de ventes terminees."""

    enabled = False

    def __init__(self) -> None:
        self.live_calls = 0

    def sold_comparables_for(self, identity: CardIdentity) -> Tuple[SoldComparable, ...]:
        return ()


class PSASalesProvider:
    """Interface PSA explicite; aucun contournement web n'est autorise."""

    status = "UNAVAILABLE"
    enabled = False

    def __init__(self) -> None:
        self.live_calls = 0

    def sold_comparables_for(self, identity: CardIdentity) -> Tuple[SoldComparable, ...]:
        return ()
