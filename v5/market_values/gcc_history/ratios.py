from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional, Sequence, Tuple

from .models import (
    CanonicalCollectible,
    ConfidenceLevel,
    GCCSale,
    Grader,
    MarketValuation,
    RatioEstimate,
    RatioObservation,
    ValuationPolicy,
    ValuationStatus,
    ValuationType,
)
from .statistics import percentile


@dataclass(frozen=True)
class RatioSupportConfig:
    minimum_exact_card_pairs: int = 1
    minimum_segment_pairs: int = 3
    minimum_broad_pairs: int = 5


def _identity_segment(identity: CanonicalCollectible) -> str:
    if identity.year is None:
        era = "era:unknown"
    elif identity.year <= 2003:
        era = "era:vintage"
    elif identity.year <= 2015:
        era = "era:mid"
    else:
        era = "era:modern"
    language = f"language:{identity.language or 'unknown'}"
    family = f"family:{identity.set_family}" if identity.set_family else "family:unknown"
    return "|".join((era, language, family))


def _deduplicated_prices(sales: Sequence[GCCSale]) -> Tuple[Decimal, ...]:
    seen: set[Tuple[object, ...]] = set()
    prices: list[Decimal] = []
    for sale in sales:
        if sale.source_id:
            key = (sale.source, sale.source_id)
        elif sale.source_url:
            key = (sale.source, sale.source_url)
        else:
            key = (
                sale.identity.key,
                sale.grader,
                sale.grade,
                sale.grade_qualifier,
                sale.price,
                sale.currency,
                sale.sale_date,
                sale.listing_title,
            )
        if key in seen:
            continue
        seen.add(key)
        prices.append(sale.price)
    return tuple(prices)


class CrossGraderRatioModel:
    """Derives conversion ratios exclusively from paired observed sales."""

    def __init__(
        self,
        calibration_sales: Sequence[GCCSale],
        config: Optional[RatioSupportConfig] = None,
    ) -> None:
        self._sales = tuple(calibration_sales)
        self.config = config or RatioSupportConfig()

    def observations(
        self,
        source_grader: Grader,
        target_grader: Grader,
        grade: Decimal,
        currency: str,
    ) -> Tuple[RatioObservation, ...]:
        buckets: Dict[
            Tuple[Tuple[object, ...], Grader], list[GCCSale]
        ] = defaultdict(list)
        identities: Dict[Tuple[object, ...], CanonicalCollectible] = {}
        for sale in self._sales:
            if (
                not sale.completed
                or sale.currency != currency
                or sale.grade != grade
                or sale.grade_qualifier is not None
                or sale.grader not in {source_grader, target_grader}
            ):
                continue
            identities[sale.identity.key] = sale.identity
            buckets[(sale.identity.key, sale.grader)].append(sale)

        observations: list[RatioObservation] = []
        for identity_key, identity in identities.items():
            source_prices = _deduplicated_prices(
                buckets.get((identity_key, source_grader), [])
            )
            target_prices = _deduplicated_prices(
                buckets.get((identity_key, target_grader), [])
            )
            source_mid = percentile(source_prices, Decimal("0.5"))
            target_mid = percentile(target_prices, Decimal("0.5"))
            if source_mid is None or target_mid is None or target_mid <= 0:
                continue
            observations.append(
                RatioObservation(
                    identity_key=identity_key,
                    segment=_identity_segment(identity),
                    ratio=source_mid / target_mid,
                    currency=currency,
                )
            )
        return tuple(observations)

    def ratio_for(
        self,
        identity: CanonicalCollectible,
        source_grader: Grader,
        target_grader: Grader,
        grade: Decimal,
        currency: str,
    ) -> Optional[RatioEstimate]:
        observations = self.observations(
            source_grader, target_grader, grade, currency
        )
        exact = [value for value in observations if value.identity_key == identity.key]
        if len(exact) >= self.config.minimum_exact_card_pairs:
            selected = exact
            hierarchy = "EXACT_CARD_OBSERVED_RATIO"
            segment = "exact-card"
        else:
            identity_segment = _identity_segment(identity)
            same_segment = [
                value for value in observations if value.segment == identity_segment
            ]
            if len(same_segment) >= self.config.minimum_segment_pairs:
                selected = same_segment
                hierarchy = "SUPPORTED_SEGMENT_RATIO"
                segment = identity_segment
            elif len(observations) >= self.config.minimum_broad_pairs:
                selected = list(observations)
                hierarchy = "BROAD_OBSERVED_RATIO"
                segment = "broad"
            else:
                return None

        ratios = [value.ratio for value in selected]
        median_ratio = percentile(ratios, Decimal("0.5"))
        low_ratio = percentile(ratios, Decimal("0.25"))
        high_ratio = percentile(ratios, Decimal("0.75"))
        if not median_ratio or not low_ratio or not high_ratio:
            return None
        if len(selected) >= 8 and high_ratio / low_ratio <= Decimal("1.15"):
            confidence = ConfidenceLevel.HIGH
        elif len(selected) >= 3 and high_ratio / low_ratio <= Decimal("1.35"):
            confidence = ConfidenceLevel.MEDIUM
        else:
            confidence = ConfidenceLevel.LOW
        return RatioEstimate(
            source_grader=source_grader,
            target_grader=target_grader,
            grade=grade,
            median_ratio=median_ratio,
            low_ratio=low_ratio,
            high_ratio=high_ratio,
            sample_size=len(selected),
            segment=segment,
            hierarchy=hierarchy,
            confidence=confidence,
        )


def proxy_market_value(
    source: MarketValuation,
    target_grader: Grader,
    target_grade: Decimal,
    ratio: RatioEstimate,
    policy: ValuationPolicy,
) -> Optional[MarketValuation]:
    if (
        source.mid is None
        or source.low is None
        or source.high is None
        or ratio.median_ratio <= 0
        or ratio.low_ratio <= 0
        or ratio.high_ratio <= 0
    ):
        return None
    confidence_order = {
        ConfidenceLevel.INSUFFICIENT: 0,
        ConfidenceLevel.LOW: 1,
        ConfidenceLevel.MEDIUM: 2,
        ConfidenceLevel.HIGH: 3,
    }
    combined_confidence = min(
        (source.confidence, ratio.confidence),
        key=lambda value: confidence_order[value],
    )
    # Cross-grader estimates are never promoted to HIGH confidence.
    if combined_confidence is ConfidenceLevel.HIGH:
        combined_confidence = ConfidenceLevel.MEDIUM
    status = ValuationStatus.PROXY_MARKET_VALUE
    exceptionally_supported_final_proxy = (
        policy is ValuationPolicy.FINAL
        and source.confidence is ConfidenceLevel.HIGH
        and ratio.confidence is ConfidenceLevel.HIGH
    )
    if (
        combined_confidence is ConfidenceLevel.LOW
        or (policy is ValuationPolicy.FINAL and not exceptionally_supported_final_proxy)
    ):
        status = ValuationStatus.MANUAL_VALIDATION_REQUIRED
    return MarketValuation(
        grader=target_grader,
        grade=target_grade,
        valuation_type=ValuationType.CROSS_GRADER_PROXY,
        status=status,
        currency=source.currency,
        low=source.low / ratio.high_ratio,
        mid=source.mid / ratio.median_ratio,
        high=source.high / ratio.low_ratio,
        confidence=combined_confidence,
        direct_comparable_count=0,
        strong_comparable_count=source.strong_comparable_count,
        ambiguous_count=source.ambiguous_count,
        rejected_count=source.rejected_count,
        statistics=source.statistics,
        source_grader=source.grader,
        ratio=ratio,
        proxy_comparable_count=(source.statistics.n if source.statistics else 0),
        source_market_low=source.low,
        source_market_mid=source.mid,
        source_market_high=source.high,
        notes=(
            "cross-grader proxy derived from empirical paired-card observations",
            f"ratio hierarchy: {ratio.hierarchy}",
        ),
        limitations=(
            "proxy is not a direct target-grader market value",
            "range combines source-market and observed-ratio uncertainty",
        ),
    )
