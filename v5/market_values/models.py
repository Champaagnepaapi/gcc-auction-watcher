from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Mapping, Optional, Tuple

from ..models import CardIdentity


MARKET_VALUES_MISSING = "MARKET_VALUES_MISSING"
MARKET_VALUE_CONFLICT = "MARKET_VALUE_CONFLICT"


class MarketLevel(str, Enum):
    UNGRADED = "UNGRADED"
    GRADE8_GENERIC = "GRADE8_GENERIC"
    GRADE9_GENERIC = "GRADE9_GENERIC"
    PSA10 = "PSA10"


class AggregationStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MISSING = MARKET_VALUES_MISSING
    CONFLICT = MARKET_VALUE_CONFLICT


def normalize_identity_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = "".join(
        character for character in text if not unicodedata.combining(character)
    )
    return " ".join(ascii_text.casefold().replace("_", " ").replace("-", " ").split())


def identity_key(identity: CardIdentity) -> Tuple[str, ...]:
    return (
        normalize_identity_text(identity.game),
        normalize_identity_text(identity.card_name),
        normalize_identity_text(identity.set),
        normalize_identity_text(identity.card_number).replace(" ", ""),
        str(identity.year or ""),
        normalize_identity_text(identity.language),
        normalize_identity_text(identity.variant),
    )


@dataclass(frozen=True)
class MarketValues:
    """Valeurs d'un fournisseur pour une seule identite expliquee.

    Les grades 8 et 9 sont volontairement nommes ``generic`` : PriceCharting
    ne promet pas qu'ils proviennent de PSA.
    """

    source: str
    currency: str
    ungraded_value: Optional[Decimal]
    grade8_generic_value: Optional[Decimal]
    grade9_generic_value: Optional[Decimal]
    psa10_value: Optional[Decimal]
    matched_identity: Optional[CardIdentity]
    match_confidence: Optional[Decimal]
    matched_product_id: Optional[str]
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    freshness: Optional[str] = None
    notes: Tuple[str, ...] = ()
    limitations: Tuple[str, ...] = ()

    @property
    def grade8_value(self) -> Optional[Decimal]:
        return self.grade8_generic_value

    @property
    def grade9_value(self) -> Optional[Decimal]:
        return self.grade9_generic_value

    def value_for(self, level: MarketLevel) -> Optional[Decimal]:
        return {
            MarketLevel.UNGRADED: self.ungraded_value,
            MarketLevel.GRADE8_GENERIC: self.grade8_generic_value,
            MarketLevel.GRADE9_GENERIC: self.grade9_generic_value,
            MarketLevel.PSA10: self.psa10_value,
        }[level]

    def has_any_value(self) -> bool:
        return any(self.value_for(level) is not None for level in MarketLevel)


@dataclass(frozen=True)
class AggregatedLevel:
    central_value: Optional[Decimal]
    low_value: Optional[Decimal]
    high_value: Optional[Decimal]
    source_count: int
    source_names: Tuple[str, ...]
    confidence: str
    disagreement: bool
    dispersion: Optional[Decimal]


@dataclass(frozen=True)
class AggregatedMarketValues:
    identity: CardIdentity
    currency: Optional[str]
    levels: Mapping[MarketLevel, AggregatedLevel]
    status: AggregationStatus
    reasons: Tuple[str, ...] = ()
    provider_values: Tuple[MarketValues, ...] = ()

    def level(self, level: MarketLevel) -> AggregatedLevel:
        return self.levels[level]
