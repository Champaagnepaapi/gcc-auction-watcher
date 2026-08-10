from __future__ import annotations

import os
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Dict, Mapping, Optional, Protocol, Sequence, Tuple

from ...models import CardIdentity
from ..models import MarketValues, normalize_identity_text
from .identity import canonical_from_card_identity, match_identity
from .models import (
    CanonicalCollectible,
    ConfidenceLevel,
    GCCMarketResult,
    GCCProviderCounters,
    GCCSale,
    Grader,
    MatchedSale,
    MatchClass,
    MarketValuation,
    ValuationPolicy,
    ValuationStatus,
    ValuationType,
)
from .normalization import GCCSaleParser
from .ratios import CrossGraderRatioModel, proxy_market_value
from .statistics import (
    CurrencyConverter,
    NoCurrencyConversion,
    RecencyWeightConfig,
    deduplicate_sales,
    estimate_direct_market,
)


class GCCSaleSource(Protocol):
    mode: str
    live_available: bool
    live_calls: int

    def fetch(self, identity: CanonicalCollectible) -> Sequence[Mapping[str, object]]:
        ...

    def calibration_records(self) -> Sequence[Mapping[str, object]]:
        ...


class UnavailableGCCSource:
    """Default source until GCC exposes a documented, stable data interface."""

    mode = "LIVE_UNAVAILABLE"
    live_available = False
    live_calls = 0

    def fetch(self, identity: CanonicalCollectible) -> Sequence[Mapping[str, object]]:
        del identity
        return ()

    def calibration_records(self) -> Sequence[Mapping[str, object]]:
        return ()


class OfflineGCCSource:
    """In-memory deterministic fixture source; it never performs network I/O."""

    mode = "OFFLINE"
    live_available = False
    live_calls = 0

    def __init__(self, records: Sequence[Mapping[str, object]]) -> None:
        self._records = tuple(dict(record) for record in records)

    def fetch(self, identity: CanonicalCollectible) -> Sequence[Mapping[str, object]]:
        # A real supported provider may perform a broad remote search here.
        # The fixture emulates a high-recall card-name query; the strict local
        # matcher remains responsible for set/number/variant inclusion.
        return tuple(
            record
            for record in self._records
            if normalize_identity_text(record.get("card_name")) == identity.card_name
        )

    def calibration_records(self) -> Sequence[Mapping[str, object]]:
        return self._records


@dataclass(frozen=True)
class GCCProviderConfig:
    enabled: bool = False
    default_currency: str = "USD"
    policy: ValuationPolicy = ValuationPolicy.DISCOVERY
    recency: RecencyWeightConfig = RecencyWeightConfig()

    @classmethod
    def from_env(cls) -> "GCCProviderConfig":
        return cls(
            enabled=os.getenv("GCC_HISTORY_ENABLED", "false").strip().casefold()
            == "true",
            default_currency=os.getenv("GCC_HISTORY_CURRENCY", "USD")
            .strip()
            .upper(),
            policy=ValuationPolicy(
                os.getenv("GCC_HISTORY_POLICY", ValuationPolicy.DISCOVERY.value)
                .strip()
                .upper()
            ),
        )


class GCCHistoryProvider:
    provider_name = "GCC History exact sold comparables"

    def __init__(
        self,
        config: Optional[GCCProviderConfig] = None,
        source: Optional[GCCSaleSource] = None,
        converter: Optional[CurrencyConverter] = None,
        today: Optional[date] = None,
    ) -> None:
        self.config = config or GCCProviderConfig.from_env()
        self.source = source or UnavailableGCCSource()
        self.converter = converter or NoCurrencyConversion()
        self.today = today or datetime.now(timezone.utc).date()
        effective_enabled = self.config.enabled and (
            self.source.live_available or self.source.mode == "OFFLINE"
        )
        self.counters = GCCProviderCounters(
            enabled=effective_enabled,
            live_available=self.source.live_available,
        )
        self._parser = GCCSaleParser()
        self._cache: Dict[Tuple[object, ...], GCCMarketResult] = {}
        self._record_cache: Dict[
            Tuple[object, ...], Tuple[Mapping[str, object], ...]
        ] = {}
        self._supported_ratio_segments: set[str] = set()
        calibration_sales, _ = self._parser.parse_records(
            self.source.calibration_records()
        )
        self._ratio_model = CrossGraderRatioModel(calibration_sales)

    @property
    def mode(self) -> str:
        return self.source.mode

    def market_for(
        self,
        identity: CardIdentity,
        currency: Optional[str] = None,
        policy: Optional[ValuationPolicy] = None,
    ) -> GCCMarketResult:
        canonical = canonical_from_card_identity(identity)
        target_currency = (currency or self.config.default_currency).upper()
        selected_policy = policy or self.config.policy
        cache_key = canonical.key + (target_currency, selected_policy.value)
        if cache_key in self._cache:
            self.counters.cache_hits += 1
            return self._cache[cache_key]

        if not self.counters.enabled or not canonical.minimum_identity_complete:
            result = GCCMarketResult(
                identity=canonical,
                policy=selected_policy,
                currency=target_currency,
                valuations={},
                market_values=None,
                match_counts={value: 0 for value in MatchClass},
                records_received=0,
                sales=(),
                notes=(f"GCC provider mode: {self.mode}",),
                limitations=(
                    "provider disabled or canonical minimum identity incomplete",
                ),
            )
            self._cache[cache_key] = result
            return result

        if canonical.key in self._record_cache:
            self.counters.cache_hits += 1
            records = self._record_cache[canonical.key]
        else:
            self.counters.queries += 1
            records = tuple(self.source.fetch(canonical))
            self._record_cache[canonical.key] = records
            self.counters.live_calls = self.source.live_calls
            self.counters.records_received += len(records)
        sales, invalid = self._parser.parse_records(records)
        self.counters.records_invalid += invalid
        matched_sales_values = []
        for sale in sales:
            identity_match = match_identity(canonical, sale)
            matched_sales_values.append(
                MatchedSale(
                    sale=replace(
                        sale,
                        match_class=identity_match.match_class,
                        match_score=identity_match.score,
                        matched_fields=identity_match.matched_fields,
                        missing_fields=identity_match.missing_fields,
                        conflicts=identity_match.conflicts,
                        match_reason=identity_match.reason,
                    ),
                    identity_match=identity_match,
                )
            )
        matched_sales = tuple(matched_sales_values)
        match_counts = {
            value: sum(
                matched.identity_match.match_class is value
                for matched in matched_sales
            )
            for value in MatchClass
        }
        self.counters.exact_matches += match_counts[MatchClass.EXACT_MATCH]
        self.counters.strong_matches += match_counts[MatchClass.STRONG_MATCH]
        self.counters.ambiguous_matches += match_counts[MatchClass.AMBIGUOUS]
        self.counters.rejected_matches += match_counts[MatchClass.REJECTED]

        valuations: Dict[Tuple[Grader, Optional[Decimal]], MarketValuation] = {}
        core_buckets = (
            (Grader.RAW, None),
            (Grader.PSA, Decimal("8")),
            (Grader.PSA, Decimal("9")),
            (Grader.PSA, Decimal("10")),
        )
        observed_buckets = {
            (matched.sale.grader, matched.sale.grade)
            for matched in matched_sales
            if matched.identity_match.match_class
            in {MatchClass.EXACT_MATCH, MatchClass.STRONG_MATCH}
            and matched.sale.grader
            in {Grader.PSA, Grader.PCA, Grader.BGS, Grader.CGC, Grader.SGC}
            and matched.sale.grade is not None
            and matched.sale.grade_qualifier is None
        }
        additional_buckets = tuple(
            sorted(
                observed_buckets.difference(core_buckets),
                key=lambda value: (value[0].value, value[1] or Decimal("0")),
            )
        )
        for grader, grade in core_buckets + additional_buckets:
            valuation = estimate_direct_market(
                matched_sales,
                grader,
                grade,
                target_currency,
                self.today,
                selected_policy,
                converter=self.converter,
                recency=self.config.recency,
            )
            if (
                valuation.valuation_type
                is ValuationType.INSUFFICIENT_MARKET_DATA
                and grader is Grader.PSA
                and (grader, grade) in core_buckets
            ):
                valuation = self._best_same_grade_proxy(
                    canonical,
                    matched_sales,
                    grade,
                    target_currency,
                    selected_policy,
                    valuation,
                )
            valuations[(grader, grade)] = valuation

        market_values = self._to_market_values(
            identity, target_currency, selected_policy, valuations
        )
        result = GCCMarketResult(
            identity=canonical,
            policy=selected_policy,
            currency=target_currency,
            valuations=valuations,
            market_values=market_values,
            match_counts=match_counts,
            records_received=len(records),
            sales=tuple(value.sale for value in matched_sales),
            notes=(
                f"GCC provider mode: {self.mode}",
                "completed/sold records only",
                "no asking-price records used",
            ),
            limitations=(
                "no documented stable GCC live interface is configured",
                "different grades are diagnostic only and never converted",
            ),
        )
        for valuation in valuations.values():
            if valuation.valuation_type is ValuationType.DIRECT_MARKET_VALUE:
                self.counters.direct_values += 1
            elif valuation.valuation_type is ValuationType.CROSS_GRADER_PROXY:
                self.counters.proxy_values += 1
            else:
                self.counters.insufficient_values += 1
            if valuation.statistics:
                self.counters.duplicates_removed += (
                    valuation.statistics.duplicates_removed
                )
                self.counters.outliers_flagged += valuation.statistics.outliers_flagged
            if valuation.status.value == "MARKET_VALUE_RANGE":
                self.counters.valuation_ranges += 1
            if valuation.mid is not None:
                if valuation.confidence is ConfidenceLevel.HIGH:
                    self.counters.high_confidence += 1
                elif valuation.confidence is ConfidenceLevel.MEDIUM:
                    self.counters.medium_confidence += 1
                elif valuation.confidence is ConfidenceLevel.LOW:
                    self.counters.low_confidence += 1
            if valuation.ratio is not None:
                self.counters.ratio_observations += valuation.ratio.sample_size
                self._supported_ratio_segments.add(valuation.ratio.segment)
        self.counters.supported_ratio_segments = len(self._supported_ratio_segments)
        self.counters.direct_raw_comps += self._direct_comp_count(
            valuations[(Grader.RAW, None)]
        )
        self.counters.direct_psa9_comps += self._direct_comp_count(
            valuations[(Grader.PSA, Decimal("9"))]
        )
        self.counters.direct_psa10_comps += self._direct_comp_count(
            valuations[(Grader.PSA, Decimal("10"))]
        )
        self.counters.pca10_comps += self._exact_bucket_count(
            matched_sales, Grader.PCA, Decimal("10"), target_currency
        )
        self.counters.bgs10_comps += self._exact_bucket_count(
            matched_sales, Grader.BGS, Decimal("10"), target_currency
        )
        self.counters.cgc10_comps += self._exact_bucket_count(
            matched_sales, Grader.CGC, Decimal("10"), target_currency
        )
        self._cache[cache_key] = result
        return result

    def values_for(self, identity: CardIdentity) -> Optional[MarketValues]:
        return self.market_for(identity).market_values

    def normalized_sales_for(
        self, identity: CardIdentity, currency: Optional[str] = None
    ) -> Sequence[GCCSale]:
        """Expose normalized, match-annotated sales without persistence."""

        return self.market_for(identity, currency).sales

    def _best_same_grade_proxy(
        self,
        identity: CanonicalCollectible,
        matched_sales: Sequence[MatchedSale],
        grade: Optional[Decimal],
        currency: str,
        policy: ValuationPolicy,
        insufficient: MarketValuation,
    ) -> MarketValuation:
        if grade is None:
            return insufficient
        candidates: list[MarketValuation] = []
        source_markets_without_ratio = 0
        for source_grader in (Grader.PCA, Grader.BGS, Grader.CGC, Grader.SGC):
            source_value = estimate_direct_market(
                matched_sales,
                source_grader,
                grade,
                currency,
                self.today,
                policy,
                converter=self.converter,
                recency=self.config.recency,
            )
            if source_value.mid is None:
                continue
            ratio = self._ratio_model.ratio_for(
                identity,
                source_grader,
                Grader.PSA,
                grade,
                currency,
            )
            if ratio is None:
                source_markets_without_ratio += 1
                continue
            proxy = proxy_market_value(
                source_value, Grader.PSA, grade, ratio, policy
            )
            if proxy is not None:
                candidates.append(proxy)
        if not candidates:
            if source_markets_without_ratio:
                self.counters.unsupported_conversions += source_markets_without_ratio
                return replace(
                    insufficient,
                    valuation_type=ValuationType.MANUAL_VALIDATION_REQUIRED,
                    status=ValuationStatus.MANUAL_VALIDATION_REQUIRED,
                    notes=(
                        "same-grade cross-grader observations exist but no empirical conversion is supported",
                    ),
                    limitations=(
                        "manual validation required; no target-grader value was fabricated",
                    ),
                )
            return insufficient
        confidence_rank = {
            ConfidenceLevel.INSUFFICIENT: 0,
            ConfidenceLevel.LOW: 1,
            ConfidenceLevel.MEDIUM: 2,
            ConfidenceLevel.HIGH: 3,
        }
        return max(
            candidates,
            key=lambda value: (
                confidence_rank[value.confidence],
                value.ratio.sample_size if value.ratio else 0,
            ),
        )

    @staticmethod
    def _direct_comp_count(valuation: MarketValuation) -> int:
        if valuation.valuation_type is not ValuationType.DIRECT_MARKET_VALUE:
            return 0
        return valuation.statistics.n if valuation.statistics else 0

    @staticmethod
    def _exact_bucket_count(
        matched_sales: Sequence[MatchedSale],
        grader: Grader,
        grade: Decimal,
        currency: str,
    ) -> int:
        bucket = tuple(
            matched
            for matched in matched_sales
            if matched.identity_match.match_class is MatchClass.EXACT_MATCH
            and matched.sale.grader is grader
            and matched.sale.grade == grade
            and matched.sale.grade_qualifier is None
            and matched.sale.currency == currency
        )
        deduplicated, _ = deduplicate_sales(bucket)
        return len(deduplicated)

    def _to_market_values(
        self,
        identity: CardIdentity,
        currency: str,
        policy: ValuationPolicy,
        valuations: Mapping[
            Tuple[Grader, Optional[Decimal]], MarketValuation
        ],
    ) -> Optional[MarketValues]:
        raw = valuations[(Grader.RAW, None)]
        psa8 = valuations[(Grader.PSA, Decimal("8"))]
        psa9 = valuations[(Grader.PSA, Decimal("9"))]
        psa10 = valuations[(Grader.PSA, Decimal("10"))]

        def usable_mid(value: MarketValuation) -> Optional[Decimal]:
            if (
                policy is ValuationPolicy.FINAL
                and value.status is ValuationStatus.MANUAL_VALIDATION_REQUIRED
            ):
                return None
            return value.mid

        if not any(usable_mid(value) is not None for value in (raw, psa8, psa9, psa10)):
            return None
        confidence_score = {
            ConfidenceLevel.HIGH: Decimal("0.90"),
            ConfidenceLevel.MEDIUM: Decimal("0.75"),
            ConfidenceLevel.LOW: Decimal("0.50"),
            ConfidenceLevel.INSUFFICIENT: Decimal("0"),
        }
        available = [
            value
            for value in (raw, psa8, psa9, psa10)
            if usable_mid(value) is not None
        ]
        match_confidence = min(
            (confidence_score[value.confidence] for value in available),
            default=Decimal("0"),
        )
        return MarketValues(
            source=self.provider_name,
            currency=currency,
            ungraded_value=usable_mid(raw),
            grade8_generic_value=usable_mid(psa8),
            grade9_generic_value=usable_mid(psa9),
            psa10_value=usable_mid(psa10),
            matched_identity=identity,
            match_confidence=match_confidence,
            matched_product_id=None,
            notes=tuple(
                f"{grader.value}:{grade if grade is not None else 'RAW'}="
                f"{valuation.valuation_type.value}/{valuation.confidence.value}"
                for (grader, grade), valuation in valuations.items()
            ),
            limitations=(
                "GRADE8_GENERIC and GRADE9_GENERIC contain PSA values only here",
                "missing grade levels remain None; no cross-grade interpolation",
            ),
        )
