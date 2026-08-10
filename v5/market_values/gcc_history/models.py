from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Mapping, Optional, Sequence, Tuple

from ..models import MarketValues


class Grader(str, Enum):
    RAW = "RAW"
    PSA = "PSA"
    PCA = "PCA"
    BGS = "BGS"
    CGC = "CGC"
    SGC = "SGC"
    UNKNOWN = "UNKNOWN"


class SaleType(str, Enum):
    AUCTION = "AUCTION"
    FIXED_PRICE = "FIXED_PRICE"
    ACCEPTED_OFFER = "ACCEPTED_OFFER"
    UNKNOWN = "UNKNOWN"


class MatchClass(str, Enum):
    EXACT_MATCH = "EXACT_MATCH"
    STRONG_MATCH = "STRONG_MATCH"
    AMBIGUOUS = "AMBIGUOUS"
    REJECTED = "REJECTED"


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT = "INSUFFICIENT"


class ValuationType(str, Enum):
    DIRECT_MARKET_VALUE = "DIRECT_MARKET_VALUE"
    CROSS_GRADER_PROXY = "CROSS_GRADER_PROXY"
    MARKET_VALUE_RANGE = "MARKET_VALUE_RANGE"
    INSUFFICIENT_MARKET_DATA = "INSUFFICIENT_MARKET_DATA"
    MANUAL_VALIDATION_REQUIRED = "MANUAL_VALIDATION_REQUIRED"


class ValuationStatus(str, Enum):
    DIRECT_MARKET_VALUE = "DIRECT_MARKET_VALUE"
    PROXY_MARKET_VALUE = "PROXY_MARKET_VALUE"
    MARKET_VALUE_RANGE = "MARKET_VALUE_RANGE"
    MANUAL_VALIDATION_REQUIRED = "MANUAL_VALIDATION_REQUIRED"
    INSUFFICIENT_MARKET_DATA = "INSUFFICIENT_MARKET_DATA"


class ValuationPolicy(str, Enum):
    DISCOVERY = "DISCOVERY"
    FINAL = "FINAL"


@dataclass(frozen=True)
class CanonicalCollectible:
    card_name: Optional[str]
    set_name: Optional[str]
    card_number: Optional[str]
    language: Optional[str] = None
    variant: Optional[str] = None
    first_edition: Optional[bool] = None
    finish: Optional[str] = None
    promo: Optional[bool] = None
    stamped: Optional[bool] = None
    special_print: Optional[str] = None
    year: Optional[int] = None
    set_family: Optional[str] = None
    category: Optional[str] = "pokemon"

    @property
    def minimum_identity_complete(self) -> bool:
        return bool(self.card_name and self.set_name and self.card_number)

    @property
    def key(self) -> Tuple[object, ...]:
        return (
            self.card_name,
            self.set_name,
            self.card_number,
            self.language,
            self.variant,
            self.first_edition,
            self.finish,
            self.promo,
            self.stamped,
            self.special_print,
            self.year,
            self.set_family,
            self.category,
        )


@dataclass(frozen=True)
class GCCSale:
    source: str
    identity: CanonicalCollectible
    grader: Grader
    grade: Optional[Decimal]
    grade_qualifier: Optional[str]
    price: Decimal
    currency: str
    sale_date: Optional[date]
    sale_type: SaleType
    completed: bool = True
    listing_title: Optional[str] = field(default=None, repr=False)
    source_id: Optional[str] = field(default=None, repr=False)
    source_url: Optional[str] = field(default=None, repr=False)
    match_class: Optional[MatchClass] = None
    match_score: Optional[int] = None
    matched_fields: Tuple[str, ...] = ()
    missing_fields: Tuple[str, ...] = ()
    conflicts: Tuple[str, ...] = ()
    match_reason: Optional[str] = None


@dataclass(frozen=True)
class IdentityMatch:
    match_class: MatchClass
    score: int
    matched_fields: Tuple[str, ...]
    missing_fields: Tuple[str, ...]
    conflicts: Tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class MatchedSale:
    sale: GCCSale
    identity_match: IdentityMatch


@dataclass(frozen=True)
class ComparableStatistics:
    raw_sales_count: int
    deduplicated_sales_count: int
    eligible_currency_sales: int
    n: int
    median: Optional[Decimal]
    weighted_median: Optional[Decimal]
    trimmed_mean: Optional[Decimal]
    mad: Optional[Decimal]
    iqr: Optional[Decimal]
    minimum: Optional[Decimal]
    maximum: Optional[Decimal]
    first_sale_date: Optional[date]
    last_sale_date: Optional[date]
    recent_30d: int
    recent_90d: int
    recent_180d: int
    recent_365d: int
    old_sales: int
    dated_sales: int
    outliers_flagged: int
    duplicates_removed: int
    recency_method: str


@dataclass(frozen=True)
class RatioEstimate:
    source_grader: Grader
    target_grader: Grader
    grade: Decimal
    median_ratio: Decimal
    low_ratio: Decimal
    high_ratio: Decimal
    sample_size: int
    segment: str
    hierarchy: str
    confidence: ConfidenceLevel


@dataclass(frozen=True)
class RatioObservation:
    identity_key: Tuple[object, ...]
    segment: str
    ratio: Decimal
    currency: str


@dataclass(frozen=True)
class MarketValuation:
    grader: Grader
    grade: Optional[Decimal]
    valuation_type: ValuationType
    status: ValuationStatus
    currency: Optional[str]
    low: Optional[Decimal]
    mid: Optional[Decimal]
    high: Optional[Decimal]
    confidence: ConfidenceLevel
    direct_comparable_count: int
    strong_comparable_count: int
    ambiguous_count: int
    rejected_count: int
    statistics: Optional[ComparableStatistics] = None
    source_grader: Optional[Grader] = None
    ratio: Optional[RatioEstimate] = None
    proxy_comparable_count: int = 0
    source_market_low: Optional[Decimal] = None
    source_market_mid: Optional[Decimal] = None
    source_market_high: Optional[Decimal] = None
    source: str = "gcc_history"
    notes: Tuple[str, ...] = ()
    limitations: Tuple[str, ...] = ()

    @property
    def newest_comp_date(self) -> Optional[date]:
        return self.statistics.last_sale_date if self.statistics else None

    @property
    def oldest_comp_date(self) -> Optional[date]:
        return self.statistics.first_sale_date if self.statistics else None

    @property
    def dispersion(self) -> Optional[Decimal]:
        return self.statistics.iqr if self.statistics else None


@dataclass
class GCCProviderCounters:
    enabled: bool = False
    live_available: bool = False
    live_calls: int = 0
    queries: int = 0
    cache_hits: int = 0
    records_received: int = 0
    records_invalid: int = 0
    exact_matches: int = 0
    strong_matches: int = 0
    ambiguous_matches: int = 0
    rejected_matches: int = 0
    direct_values: int = 0
    proxy_values: int = 0
    insufficient_values: int = 0
    duplicates_removed: int = 0
    outliers_flagged: int = 0
    direct_raw_comps: int = 0
    direct_psa9_comps: int = 0
    direct_psa10_comps: int = 0
    pca10_comps: int = 0
    bgs10_comps: int = 0
    cgc10_comps: int = 0
    valuation_ranges: int = 0
    high_confidence: int = 0
    medium_confidence: int = 0
    low_confidence: int = 0
    ratio_observations: int = 0
    supported_ratio_segments: int = 0
    unsupported_conversions: int = 0


@dataclass(frozen=True)
class GCCMarketResult:
    identity: CanonicalCollectible
    policy: ValuationPolicy
    currency: str
    valuations: Mapping[Tuple[Grader, Optional[Decimal]], MarketValuation]
    market_values: Optional[MarketValues]
    match_counts: Mapping[MatchClass, int]
    records_received: int
    sales: Sequence[GCCSale] = ()
    notes: Sequence[str] = ()
    limitations: Sequence[str] = ()

    def valuation(
        self, grader: Grader, grade: Optional[Decimal]
    ) -> Optional[MarketValuation]:
        return self.valuations.get((grader, grade))
