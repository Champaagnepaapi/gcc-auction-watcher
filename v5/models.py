from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Mapping, Optional, Sequence, Tuple


ZERO = Decimal("0")


class StructuredGradingStatus(str, Enum):
    RAW = "raw"
    GRADED = "graded"
    UNKNOWN = "unknown"


class ImageQuality(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class ScanDecision(str, Enum):
    RETAINED = "retained"
    REJECTED = "rejected"


PSA10_DEPENDENT = "PSA10_DEPENDENT"
RAW_RESALE = "RAW_RESALE"
GRADING_AFTER_VISUAL_ASSESSMENT = "GRADING_AFTER_VISUAL_ASSESSMENT"
NO_RECOMMENDED_PATH = "NONE"


@dataclass(frozen=True)
class CardIdentity:
    game: Optional[str] = None
    card_name: Optional[str] = None
    set: Optional[str] = None
    card_number: Optional[str] = None
    year: Optional[int] = None
    language: Optional[str] = None
    variant: Optional[str] = None
    rarity: Optional[str] = None
    finish: Optional[str] = None
    edition: Optional[str] = None
    illustrator: Optional[str] = None
    ambiguities: Tuple[str, ...] = ()

    def missing_required_fields(self) -> Tuple[str, ...]:
        fields = (
            ("game", self.game),
            ("card_name", self.card_name),
            ("set", self.set),
            ("card_number", self.card_number),
            ("language", self.language),
        )
        return tuple(name for name, value in fields if not value)

    def is_unambiguous_pokemon(self) -> bool:
        game = (self.game or "").casefold().replace("é", "e")
        return (
            "pokemon" in game
            and not self.missing_required_fields()
            and not self.ambiguities
        )

    def display_name(self) -> str:
        parts = [self.card_name or "Carte inconnue", self.set, self.card_number]
        return " · ".join(part for part in parts if part)


@dataclass(frozen=True)
class SellerInfo:
    username: Optional[str] = None
    feedback_percentage: Optional[str] = None
    feedback_score: Optional[int] = None


@dataclass(frozen=True)
class EbayListing:
    item_id: str
    title: str
    url: str
    price: Decimal
    currency: str
    shipping_price: Optional[Decimal]
    buying_options: Tuple[str, ...]
    end_time: Optional[datetime]
    bid_count: Optional[int]
    condition: Optional[str]
    condition_id: Optional[str]
    grading_status: StructuredGradingStatus
    seller: SellerInfo
    primary_image_url: Optional[str]
    additional_image_urls: Tuple[str, ...]
    category_id: Optional[str]
    category_name: Optional[str]
    aspects: Mapping[str, Tuple[str, ...]]
    identity: CardIdentity
    source: str = "eBay Browse API officielle"

    @property
    def image_urls(self) -> Tuple[str, ...]:
        values = []
        if self.primary_image_url:
            values.append(self.primary_image_url)
        values.extend(self.additional_image_urls)
        return tuple(dict.fromkeys(values))

    @property
    def is_auction(self) -> bool:
        return "AUCTION" in self.buying_options

    @property
    def is_buy_it_now(self) -> bool:
        return "FIXED_PRICE" in self.buying_options


@dataclass(frozen=True)
class GradeImagePair:
    """Photos explicitement designees comme recto et verso.

    L'ordre des images eBay ne prouve pas que la seconde photo est le verso.
    Cette paire doit donc venir d'une selection manuelle ou d'un futur selecteur
    d'images fiable.
    """

    front_url: Optional[str]
    back_url: Optional[str]

    def is_complete(self) -> bool:
        return bool(self.front_url and self.back_url and self.front_url != self.back_url)


@dataclass(frozen=True)
class GradeAssessment:
    predicted_grade: float
    centering: Optional[float] = None
    corners: Optional[float] = None
    edges: Optional[float] = None
    surface: Optional[float] = None
    confidence: Optional[float] = None
    issues: Tuple[str, ...] = ()
    image_quality: ImageQuality = ImageQuality.UNKNOWN
    provider: str = "unknown"


@dataclass(frozen=True)
class GradeProbabilities:
    psa10: float
    psa9: float
    psa8: float
    psa7_or_lower: float

    def __post_init__(self) -> None:
        values = self.as_tuple()
        if any(value < 0 or value > 1 for value in values):
            raise ValueError("Chaque probabilite doit etre comprise entre 0 et 1")
        if abs(sum(values) - 1.0) > 1e-9:
            raise ValueError("Les probabilites de grade doivent totaliser 1")

    def as_tuple(self) -> Tuple[float, float, float, float]:
        return (self.psa10, self.psa9, self.psa8, self.psa7_or_lower)


@dataclass(frozen=True)
class MarketValue:
    amount: Decimal
    currency: str
    sample_size: Optional[int] = None
    confidence: Optional[str] = None
    source: Optional[str] = None


@dataclass(frozen=True)
class MarketValues:
    raw: Optional[MarketValue]
    psa8: Optional[MarketValue]
    psa9: Optional[MarketValue]
    psa10: Optional[MarketValue]
    psa7_or_lower: Optional[MarketValue]

    def ev_values(self) -> Tuple[Optional[MarketValue], ...]:
        return (self.psa10, self.psa9, self.psa8, self.psa7_or_lower)

    def missing_ev_grades(self) -> Tuple[str, ...]:
        pairs = (
            ("PSA10", self.psa10),
            ("PSA9", self.psa9),
            ("PSA8", self.psa8),
            ("PSA7_OR_LOWER", self.psa7_or_lower),
        )
        return tuple(name for name, value in pairs if value is None)

    def currencies(self) -> Tuple[str, ...]:
        return tuple(
            sorted(
                {
                    value.currency
                    for value in (self.raw,) + self.ev_values()
                    if value is not None
                }
            )
        )


@dataclass(frozen=True)
class CostInputs:
    purchase_price: Optional[Decimal]
    shipping_to_buyer: Optional[Decimal]
    buyer_fees: Optional[Decimal]
    grading_fee: Optional[Decimal]
    shipping_for_grading: Optional[Decimal]
    marketplace_selling_fee_rate: Optional[Decimal]
    other_costs: Optional[Decimal]
    currency: str

    def unknown_fields(self) -> Tuple[str, ...]:
        pairs = (
            ("purchase_price", self.purchase_price),
            ("shipping_to_buyer", self.shipping_to_buyer),
            ("buyer_fees", self.buyer_fees),
            ("grading_fee", self.grading_fee),
            ("shipping_for_grading", self.shipping_for_grading),
            ("marketplace_selling_fee_rate", self.marketplace_selling_fee_rate),
            ("other_costs", self.other_costs),
        )
        return tuple(name for name, value in pairs if value is None)

    def raw_unknown_fields(self) -> Tuple[str, ...]:
        """Couts requis pour une revente RAW, hors toute depense de grading."""

        pairs = (
            ("purchase_price", self.purchase_price),
            ("shipping_to_buyer", self.shipping_to_buyer),
            ("buyer_fees", self.buyer_fees),
            ("marketplace_selling_fee_rate", self.marketplace_selling_fee_rate),
            ("other_costs", self.other_costs),
        )
        return tuple(name for name, value in pairs if value is None)

    def raw_fixed_total(self) -> Decimal:
        missing = self.raw_unknown_fields()
        if missing:
            raise ValueError("Impossible de totaliser des couts RAW inconnus")
        values = (
            self.purchase_price,
            self.shipping_to_buyer,
            self.buyer_fees,
            self.other_costs,
        )
        return sum((value for value in values if value is not None), ZERO)

    def fixed_total(self) -> Decimal:
        if self.unknown_fields():
            raise ValueError("Impossible de totaliser des couts inconnus")
        values = (
            self.purchase_price,
            self.shipping_to_buyer,
            self.buyer_fees,
            self.grading_fee,
            self.shipping_for_grading,
            self.other_costs,
        )
        return sum((value for value in values if value is not None), ZERO)

    def pre_grading_total(self) -> Decimal:
        values = (self.purchase_price, self.shipping_to_buyer, self.buyer_fees)
        if any(value is None for value in values):
            raise ValueError("Cout pre-grading incomplet")
        return sum((value for value in values if value is not None), ZERO)


@dataclass(frozen=True)
class ValuationResult:
    ev_gross: Decimal
    ev_net: Decimal
    expected_profit: Decimal
    expected_roi: Decimal
    break_even_probability_psa10: Optional[float]
    total_cost_if_graded: Decimal
    psa10_profit: Decimal
    psa9_profit: Decimal
    psa8_profit: Decimal
    worst_case_grade: str
    worst_case_profit: Decimal
    stress_grade: str
    stress_profit: Decimal
    stress_psa9_profit: Decimal


@dataclass(frozen=True)
class RawValuationResult:
    prudent_market_value: Decimal
    fixed_non_grading_costs: Decimal
    selling_fees: Decimal
    total_cost_basis: Decimal
    net_profit: Decimal
    roi_percent: Decimal


@dataclass(frozen=True)
class ScanDiagnostic:
    listing: EbayListing
    identity: CardIdentity
    decision: ScanDecision
    reasons: Tuple[str, ...]
    risk_flags: Tuple[str, ...] = ()
    assessment: Optional[GradeAssessment] = None
    probabilities: Optional[GradeProbabilities] = None
    market_values: Optional[MarketValues] = None
    valuation: Optional[ValuationResult] = None
    raw_valuation: Optional[RawValuationResult] = None
    recommended_path: str = NO_RECOMMENDED_PATH
    graded_comparison_available: bool = False
    grading_reasons: Tuple[str, ...] = ()
    costs: Optional[CostInputs] = None
    total_cost_if_graded: Optional[Decimal] = None
    psa10_profit: Optional[Decimal] = None
    psa9_profit: Optional[Decimal] = None
    psa8_profit: Optional[Decimal] = None
    confidence: str = "insuffisante"

    @property
    def retained(self) -> bool:
        return self.decision is ScanDecision.RETAINED


def decimal_from(value: object) -> Decimal:
    return Decimal(str(value))


def tuple_strings(values: Optional[Sequence[object]]) -> Tuple[str, ...]:
    if not values:
        return ()
    return tuple(str(value) for value in values)
