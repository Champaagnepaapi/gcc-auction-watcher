from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Mapping, Optional, Protocol, Sequence, Tuple

from .models import (
    ComparableStatistics,
    ConfidenceLevel,
    Grader,
    MatchedSale,
    MatchClass,
    MarketValuation,
    ValuationPolicy,
    ValuationStatus,
    ValuationType,
)


class CurrencyConverter(Protocol):
    method: str

    def convert(
        self,
        amount: Decimal,
        source_currency: str,
        target_currency: str,
        on_date: Optional[date],
    ) -> Optional[Decimal]:
        ...


class NoCurrencyConversion:
    method = "NO_CURRENCY_CONVERSION"

    def convert(
        self,
        amount: Decimal,
        source_currency: str,
        target_currency: str,
        on_date: Optional[date],
    ) -> Optional[Decimal]:
        del on_date
        return amount if source_currency == target_currency else None


class InjectedRateConverter:
    """Test/offline converter. Rates must be supplied by the caller."""

    method = "INJECTED_VALID_RATES"

    def __init__(self, rates: Mapping[Tuple[str, str], Decimal]) -> None:
        self._rates = dict(rates)

    def convert(
        self,
        amount: Decimal,
        source_currency: str,
        target_currency: str,
        on_date: Optional[date],
    ) -> Optional[Decimal]:
        del on_date
        if source_currency == target_currency:
            return amount
        rate = self._rates.get((source_currency, target_currency))
        return amount * rate if rate is not None and rate > 0 else None


@dataclass(frozen=True)
class RecencyWeightConfig:
    weight_30d: Decimal = Decimal("1")
    weight_90d: Decimal = Decimal("0.85")
    weight_180d: Decimal = Decimal("0.70")
    weight_365d: Decimal = Decimal("0.50")
    older_floor: Decimal = Decimal("0.10")
    older_period_days: int = 90
    older_period_decay: Decimal = Decimal("0.90")
    undated_weight: Decimal = Decimal("0.25")
    method: str = "CONFIGURABLE_RECENCY_BUCKETS_WITH_PROGRESSIVE_OLDER_DECAY"

    def weight(self, sale_date: Optional[date], today: date) -> Decimal:
        if sale_date is None:
            return self.undated_weight
        age = max(0, (today - sale_date).days)
        if age <= 30:
            return self.weight_30d
        if age <= 90:
            return self.weight_90d
        if age <= 180:
            return self.weight_180d
        if age <= 365:
            return self.weight_365d
        older_periods = max(
            1,
            (age - 365 + self.older_period_days - 1) // self.older_period_days,
        )
        decayed = self.weight_365d * (self.older_period_decay ** older_periods)
        return max(self.older_floor, decayed)


@dataclass(frozen=True)
class SparseRangeConfig:
    single_observation_margin: Decimal = Decimal("0.25")
    identical_sparse_margin: Decimal = Decimal("0.15")


def _percentile(values: Sequence[Decimal], percentile: Decimal) -> Optional[Decimal]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = Decimal(len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _median(values: Sequence[Decimal]) -> Optional[Decimal]:
    return _percentile(values, Decimal("0.5"))


def _weighted_median(
    values: Sequence[Tuple[Decimal, Decimal]],
) -> Optional[Decimal]:
    if not values:
        return None
    ordered = sorted(values, key=lambda value: value[0])
    total = sum((weight for _, weight in ordered), Decimal("0"))
    threshold = total / Decimal("2")
    cumulative = Decimal("0")
    for amount, weight in ordered:
        cumulative += weight
        if cumulative >= threshold:
            return amount
    return ordered[-1][0]


def _trimmed_mean(values: Sequence[Decimal]) -> Optional[Decimal]:
    if not values:
        return None
    ordered = sorted(values)
    trim = int(Decimal(len(ordered)) * Decimal("0.10")) if len(ordered) >= 10 else 0
    kept = ordered[trim : len(ordered) - trim] if trim else ordered
    return sum(kept, Decimal("0")) / Decimal(len(kept))


def deduplicate_sales(
    sales: Sequence[MatchedSale],
) -> Tuple[Tuple[MatchedSale, ...], int]:
    seen: set[Tuple[object, ...]] = set()
    kept: list[MatchedSale] = []
    removed = 0
    for matched in sales:
        sale = matched.sale
        if sale.source_id:
            key = ("source_id", sale.source, sale.source_id)
        elif sale.source_url:
            key = ("source_url", sale.source, sale.source_url)
        elif sale.listing_title and sale.sale_date:
            key = (
                "fallback",
                sale.identity.key,
                sale.grader,
                sale.grade,
                sale.grade_qualifier,
                sale.price,
                sale.currency,
                sale.sale_date,
                sale.listing_title.casefold().strip(),
            )
        else:
            # Without a stable identifier and sufficient fallback evidence,
            # retaining a possible duplicate is safer than deleting a real sale.
            kept.append(matched)
            continue
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        kept.append(matched)
    return tuple(kept), removed


def _flag_outlier_indexes(values: Sequence[Decimal]) -> set[int]:
    if len(values) < 5:
        return set()
    median = _median(values)
    if median is None:
        return set()
    deviations = [abs(value - median) for value in values]
    mad = _median(deviations) or Decimal("0")
    mad_flagged: set[int] = set()
    if mad > 0:
        for index, value in enumerate(values):
            modified_z = Decimal("0.6745") * abs(value - median) / mad
            if modified_z > Decimal("3.5"):
                mad_flagged.add(index)
    q1 = _percentile(values, Decimal("0.25"))
    q3 = _percentile(values, Decimal("0.75"))
    iqr_flagged: set[int] = set()
    if q1 is not None and q3 is not None and q3 > q1:
        iqr = q3 - q1
        lower = q1 - Decimal("3") * iqr
        upper = q3 + Decimal("3") * iqr
        for index, value in enumerate(values):
            if value < lower or value > upper:
                iqr_flagged.add(index)
        # Require agreement between two robust tests when both are available.
        # This avoids deleting a plausible historical regime merely because it
        # differs from a tight recent cluster.
        return mad_flagged & iqr_flagged if mad > 0 else iqr_flagged
    return mad_flagged


def _confidence(
    n: int,
    recent_90d: int,
    recent_180d: int,
    iqr: Optional[Decimal],
    median: Optional[Decimal],
    exact_only: bool,
) -> ConfidenceLevel:
    if n == 0:
        return ConfidenceLevel.INSUFFICIENT
    relative_iqr = None
    if median and median > 0 and iqr is not None:
        relative_iqr = iqr / median
    if exact_only and n >= 8 and recent_90d >= 5 and (
        relative_iqr is None or relative_iqr <= Decimal("0.20")
    ):
        return ConfidenceLevel.HIGH
    if exact_only and n >= 4 and recent_180d >= 2 and (
        relative_iqr is None or relative_iqr <= Decimal("0.40")
    ):
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def estimate_direct_market(
    matched_sales: Sequence[MatchedSale],
    grader: Grader,
    grade: Optional[Decimal],
    currency: str,
    today: date,
    policy: ValuationPolicy,
    converter: Optional[CurrencyConverter] = None,
    recency: Optional[RecencyWeightConfig] = None,
    sparse_range: Optional[SparseRangeConfig] = None,
    grade_qualifier: Optional[str] = None,
) -> MarketValuation:
    converter = converter or NoCurrencyConversion()
    recency = recency or RecencyWeightConfig()
    sparse_range = sparse_range or SparseRangeConfig()
    eligible_match_classes = {MatchClass.EXACT_MATCH}
    if policy is ValuationPolicy.DISCOVERY:
        eligible_match_classes.add(MatchClass.STRONG_MATCH)

    bucket = [
        matched
        for matched in matched_sales
        if matched.identity_match.match_class in eligible_match_classes
        and matched.sale.grader is grader
        and matched.sale.grade == grade
        and matched.sale.grade_qualifier == grade_qualifier
        and matched.sale.completed
    ]
    raw_sales_count = len(bucket)
    bucket, duplicates_removed = deduplicate_sales(bucket)
    deduplicated_sales_count = len(bucket)
    converted: list[Tuple[MatchedSale, Decimal]] = []
    excluded_currencies: set[str] = set()
    for matched in bucket:
        amount = converter.convert(
            matched.sale.price,
            matched.sale.currency,
            currency,
            matched.sale.sale_date,
        )
        if amount is None:
            excluded_currencies.add(matched.sale.currency)
        else:
            converted.append((matched, amount))

    exact_count = sum(
        1
        for matched, _ in converted
        if matched.identity_match.match_class is MatchClass.EXACT_MATCH
    )
    strong_count = len(converted) - exact_count
    all_ambiguous = sum(
        matched.identity_match.match_class is MatchClass.AMBIGUOUS
        for matched in matched_sales
    )
    all_rejected = sum(
        matched.identity_match.match_class is MatchClass.REJECTED
        for matched in matched_sales
    )
    if not converted:
        limitations = ["no same-currency completed comparable in the exact grader/grade bucket"]
        if excluded_currencies:
            limitations.append(
                "currencies segregated without an injected converter: "
                + ",".join(sorted(excluded_currencies))
            )
        return MarketValuation(
            grader=grader,
            grade=grade,
            valuation_type=ValuationType.INSUFFICIENT_MARKET_DATA,
            status=ValuationStatus.INSUFFICIENT_MARKET_DATA,
            currency=currency,
            low=None,
            mid=None,
            high=None,
            confidence=ConfidenceLevel.INSUFFICIENT,
            direct_comparable_count=0,
            strong_comparable_count=0,
            ambiguous_count=all_ambiguous,
            rejected_count=all_rejected,
            limitations=tuple(limitations),
        )

    amounts = [amount for _, amount in converted]
    flagged_indexes = _flag_outlier_indexes(amounts)
    kept = [
        pair for index, pair in enumerate(converted) if index not in flagged_indexes
    ]
    if not kept:
        kept = converted
        flagged_indexes = set()
    kept_amounts = [amount for _, amount in kept]
    median = _median(kept_amounts)
    q1 = _percentile(kept_amounts, Decimal("0.25"))
    q3 = _percentile(kept_amounts, Decimal("0.75"))
    mad = (
        _median([abs(amount - median) for amount in kept_amounts])
        if median is not None
        else None
    )
    dated = [matched.sale.sale_date for matched, _ in kept if matched.sale.sale_date]
    ages = [max(0, (today - value).days) for value in dated]
    weighted_median = _weighted_median(
        [
            (amount, recency.weight(matched.sale.sale_date, today))
            for matched, amount in kept
        ]
    )
    n = len(kept)
    sparse_range_applied = False
    if n == 1:
        low = kept_amounts[0] * (Decimal("1") - sparse_range.single_observation_margin)
        high = kept_amounts[0] * (Decimal("1") + sparse_range.single_observation_margin)
        sparse_range_applied = True
    elif n <= 3:
        low, high = min(kept_amounts), max(kept_amounts)
        if low == high:
            low *= Decimal("1") - sparse_range.identical_sparse_margin
            high *= Decimal("1") + sparse_range.identical_sparse_margin
            sparse_range_applied = True
    else:
        low, high = q1, q3
    recent_30d = sum(age <= 30 for age in ages)
    recent_90d = sum(age <= 90 for age in ages)
    recent_180d = sum(age <= 180 for age in ages)
    recent_365d = sum(age <= 365 for age in ages)
    exact_only = strong_count == 0
    confidence = _confidence(
        n,
        recent_90d,
        recent_180d,
        (q3 - q1) if q1 is not None and q3 is not None else None,
        median,
        exact_only,
    )
    status = ValuationStatus.DIRECT_MARKET_VALUE
    valuation_type = ValuationType.DIRECT_MARKET_VALUE
    if strong_count:
        status = ValuationStatus.MANUAL_VALIDATION_REQUIRED
        valuation_type = ValuationType.MARKET_VALUE_RANGE
    elif policy is ValuationPolicy.FINAL and confidence is ConfidenceLevel.LOW:
        status = ValuationStatus.MANUAL_VALIDATION_REQUIRED
    elif n <= 2:
        status = ValuationStatus.MARKET_VALUE_RANGE

    statistics = ComparableStatistics(
        raw_sales_count=raw_sales_count,
        deduplicated_sales_count=deduplicated_sales_count,
        eligible_currency_sales=len(converted),
        n=n,
        median=median,
        weighted_median=weighted_median,
        trimmed_mean=_trimmed_mean(kept_amounts),
        mad=mad,
        iqr=(q3 - q1) if q1 is not None and q3 is not None else None,
        minimum=min(kept_amounts),
        maximum=max(kept_amounts),
        first_sale_date=min(dated) if dated else None,
        last_sale_date=max(dated) if dated else None,
        recent_30d=recent_30d,
        recent_90d=recent_90d,
        recent_180d=recent_180d,
        recent_365d=recent_365d,
        old_sales=n - recent_365d,
        dated_sales=len(dated),
        outliers_flagged=len(flagged_indexes),
        duplicates_removed=duplicates_removed,
        recency_method=recency.method,
    )
    limitations = []
    if excluded_currencies:
        limitations.append(
            "excluded currencies without injected conversion: "
            + ",".join(sorted(excluded_currencies))
        )
    if flagged_indexes:
        limitations.append("obvious robust outliers excluded from the central estimate")
    if sparse_range_applied:
        limitations.append(
            "sparse-sample uncertainty band applied; it is not a confidence interval"
        )
    return MarketValuation(
        grader=grader,
        grade=grade,
        valuation_type=valuation_type,
        status=status,
        currency=currency,
        low=low,
        mid=weighted_median or median,
        high=high,
        confidence=confidence,
        direct_comparable_count=exact_count,
        strong_comparable_count=strong_count,
        ambiguous_count=all_ambiguous,
        rejected_count=all_rejected,
        statistics=statistics,
        notes=(
            f"primary estimator: recency-weighted median ({recency.method})",
            f"currency method: {converter.method}",
        ),
        limitations=tuple(limitations),
    )


def percentile(values: Sequence[Decimal], value: Decimal) -> Optional[Decimal]:
    """Public deterministic percentile helper used by empirical ratio models."""

    return _percentile(values, value)
