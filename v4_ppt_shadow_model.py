"""Pure shadow-only PokemonPriceTracker valuation model for V4.

No function in this module can mutate V4 economics or notify the user. PPT eBay
history is always classified as SOLD_AGGREGATED, never SOLD_ITEM_LEVEL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import sqrt
from statistics import median
from typing import Mapping, Sequence

EVIDENCE_CLASS = "SOLD_AGGREGATED"
UPSTREAM_CLASS = "EBAY_SOLD_AGGREGATED_VIA_PPT"
BASE_REQUIRED_DISCOUNT_PCT = 30.0
KINETIC_FLOOR_DISCOUNT_PCT = 20.0
MIN_STRONG_SALES = 3
MAX_STRONG_LAST_SALE_AGE_DAYS = 30
MIN_KINETIC_SALES = 10
MAX_KINETIC_LAST_SALE_AGE_DAYS = 14
MAX_KINETIC_BONUS_PP = 10.0
MAX_HISTORY_CV = 0.35


@dataclass(frozen=True)
class DailyGradePoint:
    date: str
    count: int
    average_price_usd: float | None
    total_value_usd: float | None = None


@dataclass(frozen=True)
class GradedAggregate:
    grader: str
    grade: str
    sales_count: int
    average_price_usd: float | None
    median_price_usd: float | None
    smart_market_price_usd: float | None
    last_sale_date: str | None
    market_trend: str | None = None


@dataclass(frozen=True)
class ShadowInput:
    identity_exact: bool
    microvariant_compatible: bool
    grader: str
    grade: str
    gcc_price_eur: float
    usd_per_eur: float
    gcc_exact_sold_count: int = 0


@dataclass(frozen=True)
class ShadowMetrics:
    evidence_class: str
    upstream_class: str
    eligible: bool
    block_reason: str | None
    evidence_strength: str
    provider_fair_value_usd: float | None
    recent_level_30d_usd: float | None
    recent_level_90d_usd: float | None
    fair_value_usd: float | None
    fair_value_eur: float | None
    discount_to_external_pct: float | None
    sales_count: int
    last_sale_age_days: int | None
    momentum_30d_pct: float | None
    momentum_90d_pct: float | None
    momentum_180d_pct: float | None
    sales_velocity_30d: float
    sales_velocity_90d: float
    sales_velocity_180d: float
    history_cv: float | None
    kinetic_bonus_pp: float
    shadow_required_discount_pct: float
    baseline_30pct_signal: bool
    kinetic_shadow_signal: bool
    gcc_history_present: bool


def _positive(value: object) -> float | None:
    try:
        number = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    if number is None or number <= 0:
        return None
    return number


def _grade_text(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "").strip()
    if number.is_integer():
        return str(int(number))
    return str(number).rstrip("0").rstrip(".")


def _parse_day(text: str | None) -> date | None:
    if not text:
        return None
    raw = str(text).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None


def _weighted_level(points: Sequence[DailyGradePoint]) -> float | None:
    numerator = 0.0
    denominator = 0
    for point in points:
        count = max(0, int(point.count or 0))
        average = _positive(point.average_price_usd)
        if count <= 0 or average is None:
            continue
        numerator += average * count
        denominator += count
    return numerator / denominator if denominator else None


def _window(points: Sequence[DailyGradePoint], days: int) -> list[DailyGradePoint]:
    parsed = [(point, _parse_day(point.date)) for point in points]
    parsed = [(point, when) for point, when in parsed if when is not None]
    if not parsed:
        return []
    anchor = max(when for _, when in parsed)
    return [point for point, when in parsed if 0 <= (anchor - when).days < days]


def _window_sales(points: Sequence[DailyGradePoint], days: int) -> int:
    return sum(max(0, int(point.count or 0)) for point in _window(points, days))


def _momentum(points: Sequence[DailyGradePoint], days: int) -> float | None:
    selected = _window(points, days)
    dated = sorted(
        ((point, _parse_day(point.date)) for point in selected),
        key=lambda item: item[1] or date.min,
    )
    if len(dated) < 4 or sum(max(0, int(p.count or 0)) for p, _ in dated) < 4:
        return None
    midpoint = len(dated) // 2
    old = _weighted_level([point for point, _ in dated[:midpoint]])
    new = _weighted_level([point for point, _ in dated[midpoint:]])
    if old is None or new is None or old <= 0:
        return None
    return (new / old - 1.0) * 100.0


def _velocity(points: Sequence[DailyGradePoint], days: int) -> float:
    return _window_sales(points, days) / max(1, days) * 30.0


def _history_cv(points: Sequence[DailyGradePoint]) -> float | None:
    values: list[tuple[float, int]] = []
    for point in _window(points, 180):
        average = _positive(point.average_price_usd)
        count = max(0, int(point.count or 0))
        if average is not None and count > 0:
            values.append((average, count))
    if not values:
        return None
    total_weight = sum(weight for _, weight in values)
    mean = sum(value * weight for value, weight in values) / total_weight
    if mean <= 0:
        return None
    variance = sum(weight * (value - mean) ** 2 for value, weight in values) / total_weight
    return sqrt(variance) / mean


def provider_fair_value_usd(aggregate: GradedAggregate) -> float | None:
    med = _positive(aggregate.median_price_usd)
    smart = _positive(aggregate.smart_market_price_usd)
    avg = _positive(aggregate.average_price_usd)
    if med is None and smart is None and avg is None:
        return None
    anchors = [value for value in (med, smart) if value is not None]
    if not anchors:
        return avg
    low, high = min(anchors), max(anchors)
    clipped_average = None if avg is None else min(max(avg, low * 0.80), high * 1.20)
    weighted: list[tuple[float, float]] = []
    if med is not None:
        weighted.append((med, 0.50))
    if smart is not None:
        weighted.append((smart, 0.35))
    if clipped_average is not None:
        weighted.append((clipped_average, 0.15))
    total_weight = sum(weight for _, weight in weighted)
    return sum(value * weight for value, weight in weighted) / total_weight


def temporal_fair_value_usd(
    aggregate: GradedAggregate,
    history: Sequence[DailyGradePoint],
) -> tuple[float | None, float | None, float | None]:
    """Return current FV plus 30/90d sold levels from the same PPT upstream."""
    provider = provider_fair_value_usd(aggregate)
    recent30 = _weighted_level(_window(history, 30)) if _window_sales(history, 30) >= 3 else None
    recent90 = _weighted_level(_window(history, 90)) if _window_sales(history, 90) >= 3 else None
    anchors = [value for value in (provider, recent30, recent90) if value is not None]
    if not anchors:
        return provider, recent30, recent90
    return float(median(anchors)), recent30, recent90


def kinetic_bonus_pp(
    *,
    aggregate: GradedAggregate,
    momentum_30d: float | None,
    momentum_90d: float | None,
    momentum_180d: float | None,
    last_sale_age_days: int | None,
    history_cv: float | None,
) -> float:
    if aggregate.sales_count < MIN_KINETIC_SALES:
        return 0.0
    if last_sale_age_days is None or last_sale_age_days > MAX_KINETIC_LAST_SALE_AGE_DAYS:
        return 0.0
    if history_cv is not None and history_cv > MAX_HISTORY_CV:
        return 0.0
    if momentum_30d is None or momentum_90d is None:
        return 0.0
    if momentum_30d <= 5.0 or momentum_90d <= 0.0:
        return 0.0
    momentum180 = max(0.0, momentum_180d or 0.0)
    raw = 0.20 * max(0.0, momentum_30d) + 0.08 * max(0.0, momentum_90d) + 0.02 * momentum180
    return min(MAX_KINETIC_BONUS_PP, max(0.0, raw))


def analyze_shadow(
    target: ShadowInput,
    aggregate: GradedAggregate,
    history: Sequence[DailyGradePoint],
    *,
    today: date | None = None,
) -> ShadowMetrics:
    today = today or date.today()
    eligible = bool(
        target.identity_exact
        and target.microvariant_compatible
        and target.grader.strip()
        and target.grade.strip()
        and aggregate.grader.strip().upper() == target.grader.strip().upper()
        and _grade_text(aggregate.grade) == _grade_text(target.grade)
    )
    if not eligible:
        return ShadowMetrics(
            EVIDENCE_CLASS, UPSTREAM_CLASS, False,
            "IDENTITY_OR_GRADE_OR_MICROVARIANT_NOT_EXACT", "UNAVAILABLE",
            None, None, None, None, None, None, aggregate.sales_count,
            None, None, None, None, 0.0, 0.0, 0.0, None, 0.0,
            BASE_REQUIRED_DISCOUNT_PCT, False, False,
            target.gcc_exact_sold_count > 0,
        )

    fair_usd, recent30, recent90 = temporal_fair_value_usd(aggregate, history)
    provider_fv = provider_fair_value_usd(aggregate)
    fair_eur = fair_usd / target.usd_per_eur if fair_usd is not None and target.usd_per_eur > 0 else None
    discount = None
    if fair_eur is not None and fair_eur > 0 and target.gcc_price_eur >= 0:
        discount = (fair_eur - target.gcc_price_eur) / fair_eur * 100.0

    last_day = _parse_day(aggregate.last_sale_date)
    last_age = (today - last_day).days if last_day and today >= last_day else None
    momentum30 = _momentum(history, 30)
    momentum90 = _momentum(history, 90)
    momentum180 = _momentum(history, 180)
    cv = _history_cv(history)
    bonus = kinetic_bonus_pp(
        aggregate=aggregate,
        momentum_30d=momentum30,
        momentum_90d=momentum90,
        momentum_180d=momentum180,
        last_sale_age_days=last_age,
        history_cv=cv,
    )
    required = max(KINETIC_FLOOR_DISCOUNT_PCT, BASE_REQUIRED_DISCOUNT_PCT - bonus)
    strong = bool(
        fair_eur is not None
        and aggregate.sales_count >= MIN_STRONG_SALES
        and last_age is not None
        and last_age <= MAX_STRONG_LAST_SALE_AGE_DAYS
    )
    return ShadowMetrics(
        evidence_class=EVIDENCE_CLASS,
        upstream_class=UPSTREAM_CLASS,
        eligible=True,
        block_reason=None,
        evidence_strength="STRONG" if strong else "WEAK",
        provider_fair_value_usd=provider_fv,
        recent_level_30d_usd=recent30,
        recent_level_90d_usd=recent90,
        fair_value_usd=fair_usd,
        fair_value_eur=fair_eur,
        discount_to_external_pct=discount,
        sales_count=aggregate.sales_count,
        last_sale_age_days=last_age,
        momentum_30d_pct=momentum30,
        momentum_90d_pct=momentum90,
        momentum_180d_pct=momentum180,
        sales_velocity_30d=_velocity(history, 30),
        sales_velocity_90d=_velocity(history, 90),
        sales_velocity_180d=_velocity(history, 180),
        history_cv=cv,
        kinetic_bonus_pp=bonus,
        shadow_required_discount_pct=required,
        baseline_30pct_signal=bool(strong and discount is not None and discount >= BASE_REQUIRED_DISCOUNT_PCT),
        kinetic_shadow_signal=bool(strong and discount is not None and discount >= required),
        gcc_history_present=target.gcc_exact_sold_count > 0,
    )


def grader_premium_vs_psa_pct(target_fv: float | None, psa_fv: float | None) -> float | None:
    if target_fv is None or psa_fv is None or target_fv <= 0 or psa_fv <= 0:
        return None
    return (target_fv / psa_fv - 1.0) * 100.0


def temporal_grader_premium_vs_psa(
    target_history: Sequence[DailyGradePoint],
    psa_history: Sequence[DailyGradePoint],
) -> Mapping[str, float | None]:
    output: dict[str, float | None] = {}
    for days in (30, 90, 180):
        target = _weighted_level(_window(target_history, days))
        psa = _weighted_level(_window(psa_history, days))
        output[f"{days}d"] = grader_premium_vs_psa_pct(target, psa)
    return output
