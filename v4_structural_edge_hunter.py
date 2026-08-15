"""Structural Edge Hunter V2 for V4.

This module surfaces structural pricing inefficiencies without changing V4
economics.  Every signal is secondary context / prioritization only:

- cross-market SOLD lag;
- grader lag versus PSA with a historical spread;
- stale seller repricing (only with explicit seller metadata);
- liquidity breakout;
- relative-grade anomaly;
- same-card active-inventory anomaly;
- expected-profit information / ranking.

Grade/metadata mislisting remains owned by the existing cert-first Mislisted
Slab Hunter.  Active asks are never SOLD.  Cardmarket RAW is never promoted to
a graded SOLD comparable.

No signal here can create or suppress an opportunity, alter fair value,
max_recommended, discount thresholds, or perform any transaction.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Optional

import watcher
import v4_roi_efficiency as roi
import v4_smart_external_priority as smart_priority


@dataclass(frozen=True)
class CrossMarketLagSignal:
    external_recent_median: float
    gcc_reference_median: float
    external_recent_count: int
    gcc_reference_count: int
    market_lag_pct: float
    price_gap_pct: float
    sources: tuple[str, ...]


@dataclass(frozen=True)
class GraderLagSignal:
    target_grader: str
    grade: float
    historical_target_per_psa_ratio: float
    psa_baseline_median: float
    psa_recent_median: float
    psa_momentum_pct: float
    implied_target_value: float
    current_gap_pct: float
    target_reference_count: int
    psa_baseline_count: int
    psa_recent_count: int


@dataclass(frozen=True)
class LiquidityBreakoutSignal:
    recent_count: int
    prior_count: int
    recent_median: float
    prior_median: Optional[float]
    price_gap_pct: float
    recent_vs_prior_pct: Optional[float]


@dataclass(frozen=True)
class RelativeGradeAnomalySignal:
    target_grade: float
    lower_grade: float
    lower_grade_median: float
    lower_grade_count: int
    inversion_pct: float


@dataclass(frozen=True)
class SameCardInventorySignal:
    lowest_ask: float
    next_exact_ask: float
    inventory_gap_pct: float
    recent_sold_median: float
    recent_sold_count: int
    sold_gap_pct: float
    exact_active_count: int


@dataclass(frozen=True)
class StaleSellerRepricingSignal:
    seller_key: str
    active_fixed_count: int
    stale_fixed_count: int
    listing_age_days: float
    momentum_pct: float
    price_gap_pct: float


@dataclass(frozen=True)
class ExpectedProfitInfo:
    central_profit_eur: float
    conservative_profit_eur: float
    central_roi_pct: float
    conservative_roi_pct: float
    assumed_fee_pct: float
    assumed_fixed_cost_eur: float
    rank: int = 0
    total_ranked: int = 0


_ORIGINAL_FIXED_RESULT_TO_LOT = None
_ORIGINAL_PROCESS = None
_ORIGINAL_NOTIFY = None
_ORIGINAL_PRIORITY_SCORE = None
_RUN_FIXED_LOTS: dict[str, watcher.Lot] = {}
_INSTALLED = False


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _seller_key_from_result(result: object) -> str:
    """Return only an explicit seller identity; never infer from unrelated IDs."""
    if not isinstance(result, dict):
        return ""

    def clean(value: object) -> str:
        text = str(value or "").strip()
        return text if text and len(text) <= 160 else ""

    for container_name in ("seller", "owner"):
        container = result.get(container_name)
        if not isinstance(container, dict):
            continue
        for key in ("id", "userId", "sellerId", "username", "nickname", "displayName"):
            value = clean(container.get(key))
            if value:
                return f"{container_name}:{key}:{value}"

    for key in ("sellerId", "sellerUserId", "sellerUsername"):
        value = clean(result.get(key))
        if value:
            return f"result:{key}:{value}"

    item = result.get("item")
    if isinstance(item, dict):
        for container_name in ("seller", "owner"):
            container = item.get(container_name)
            if not isinstance(container, dict):
                continue
            for key in ("id", "userId", "sellerId", "username", "nickname", "displayName"):
                value = clean(container.get(key))
                if value:
                    return f"item.{container_name}:{key}:{value}"
        for key in ("sellerId", "sellerUserId", "sellerUsername"):
            value = clean(item.get(key))
            if value:
                return f"item:{key}:{value}"
    return ""


def _fixed_result_with_edge_metadata(result, item_url, coverage, **kwargs):
    lot = _ORIGINAL_FIXED_RESULT_TO_LOT(result, item_url, coverage, **kwargs)
    if lot is None:
        return None
    seller_key = _seller_key_from_result(result)
    if seller_key:
        setattr(lot, "gcc_seller_key", seller_key)
    _RUN_FIXED_LOTS[lot.url] = lot
    return lot


def _grade(lot: watcher.Lot) -> Optional[float]:
    return watcher._target_grade(lot)


def _same_grader_grade_sale(
    lot: watcher.Lot,
    sale: watcher.ComparableSale,
    *,
    allow_other_grade: bool = False,
) -> bool:
    if not isinstance(sale, watcher.ComparableSale):
        return False
    if not sale.exact_card or sale.price <= 0 or sale.grade_qualifier:
        return False
    if (sale.grader or "").strip().upper() != (lot.grader or "").strip().upper():
        return False
    target = _grade(lot)
    if target is None or sale.grade is None:
        return False
    return allow_other_grade or abs(float(sale.grade) - float(target)) <= 1e-9


def _dated_exact_target_sales(
    lot: watcher.Lot,
    sales: list[watcher.ComparableSale],
) -> list[watcher.ComparableSale]:
    return [
        sale for sale in sales
        if _same_grader_grade_sale(lot, sale)
        and _aware(sale.sold_at) is not None
    ]


def _dated_exact_external_target_sales(
    lot: watcher.Lot,
    sales: list[watcher.ComparableSale],
) -> list[watcher.ComparableSale]:
    result = []
    for sale in sales:
        if not isinstance(sale, watcher.ComparableSale) or sale.sold_at is None:
            continue
        try:
            exact = watcher.external_comparable_is_exact(lot, sale)
        except Exception:
            exact = False
        if exact:
            result.append(sale)
    return result


def _window_prices(
    sales: list[watcher.ComparableSale],
    now: datetime,
    *,
    min_age_days: float = 0.0,
    max_age_days: float,
) -> list[float]:
    current = _aware(now) or datetime.now(timezone.utc)
    values = []
    for sale in sales:
        sold_at = _aware(sale.sold_at)
        if sold_at is None or sold_at > current:
            continue
        age = (current - sold_at).total_seconds() / 86400.0
        if min_age_days < age <= max_age_days:
            values.append(float(sale.price))
        elif min_age_days == 0.0 and 0 <= age <= max_age_days:
            values.append(float(sale.price))
    return values


def _pct_below(reference: float, price: object) -> float:
    try:
        current = float(price)
    except (TypeError, ValueError):
        return 0.0
    if reference <= 0 or current <= 0 or current >= reference:
        return 0.0
    return (reference - current) / reference * 100.0


def cross_market_lag_signal(
    op: watcher.Opportunity,
    now: Optional[datetime] = None,
) -> Optional[CrossMarketLagSignal]:
    """Detect a recent exact graded SOLD market running above GCC.

    Cardmarket/TCGplayer RAW is intentionally excluded: it is not a graded SOLD.
    """
    current = _aware(now) or datetime.now(timezone.utc)
    recent_days = max(30, _env_int("V4_EDGE_CROSS_MARKET_RECENT_DAYS", 90))
    min_external = max(2, _env_int("V4_EDGE_CROSS_MARKET_MIN_EXTERNAL_SOLD", 2))
    min_gcc = max(2, _env_int("V4_EDGE_CROSS_MARKET_MIN_GCC_SOLD", 2))
    min_lag = _env_float("V4_EDGE_CROSS_MARKET_MIN_LAG_PCT", 15.0)
    min_price_gap = _env_float("V4_EDGE_CROSS_MARKET_MIN_PRICE_GAP_PCT", 15.0)

    gcc_sales = _dated_exact_target_sales(op.lot, op.gcc_comparables)
    external_sales = _dated_exact_external_target_sales(
        op.lot,
        list(op.ebay_comparables or []) + list(op.psa_apr_comparables or []),
    )
    gcc_recent = _window_prices(gcc_sales, current, max_age_days=recent_days)
    gcc_all = _window_prices(gcc_sales, current, max_age_days=365)
    gcc_prices = gcc_recent if len(gcc_recent) >= min_gcc else gcc_all
    external_recent = _window_prices(
        external_sales, current, max_age_days=recent_days
    )
    if len(gcc_prices) < min_gcc or len(external_recent) < min_external:
        return None

    gcc_med = median(gcc_prices)
    ext_med = median(external_recent)
    if gcc_med <= 0 or ext_med <= 0 or ext_med <= gcc_med:
        return None
    lag = (ext_med / gcc_med - 1.0) * 100.0
    price_gap = _pct_below(ext_med, op.lot.current_price)
    if lag < min_lag or price_gap < min_price_gap:
        return None

    sources = tuple(
        sorted({(sale.source or "external").upper() for sale in external_sales})
    )
    return CrossMarketLagSignal(
        round(ext_med, 2),
        round(gcc_med, 2),
        len(external_recent),
        len(gcc_prices),
        round(lag, 1),
        round(price_gap, 1),
        sources,
    )


def _sales_for_grader_grade(
    sales: list[watcher.ComparableSale],
    grader: str,
    grade: float,
) -> list[watcher.ComparableSale]:
    grader = grader.strip().upper()
    result = []
    for sale in sales:
        if (
            isinstance(sale, watcher.ComparableSale)
            and sale.exact_card
            and sale.price > 0
            and sale.sold_at is not None
            and not sale.grade_qualifier
            and (sale.grader or "").strip().upper() == grader
            and sale.grade is not None
            and abs(float(sale.grade) - grade) <= 1e-9
        ):
            result.append(sale)
    return result


def grader_lag_signal(
    candidate,
    now: Optional[datetime] = None,
) -> Optional[GraderLagSignal]:
    """Detect PCA/CCC lagging a PSA move using a proven historical spread."""
    lot = candidate.lot
    grader = (lot.grader or "").strip().upper()
    target_grade = _grade(lot)
    if grader not in {"PCA", "CCC"} or target_grade is None:
        return None

    current = _aware(now) or datetime.now(timezone.utc)
    recent_days = max(30, _env_int("V4_EDGE_GRADER_LAG_RECENT_DAYS", 90))
    baseline_days = max(recent_days + 90, _env_int("V4_EDGE_GRADER_LAG_BASELINE_DAYS", 365))
    min_each = max(2, _env_int("V4_EDGE_GRADER_LAG_MIN_SALES", 2))
    min_psa_momentum = _env_float("V4_EDGE_GRADER_LAG_MIN_PSA_MOMENTUM_PCT", 15.0)
    min_gap = _env_float("V4_EDGE_GRADER_LAG_MIN_GAP_PCT", 20.0)

    all_sales = list(getattr(candidate.gcc, "sales", []) or [])
    target_sales = _sales_for_grader_grade(all_sales, grader, target_grade)
    psa_sales = _sales_for_grader_grade(all_sales, "PSA", target_grade)

    target_old = _window_prices(
        target_sales, current, min_age_days=recent_days, max_age_days=baseline_days
    )
    psa_old = _window_prices(
        psa_sales, current, min_age_days=recent_days, max_age_days=baseline_days
    )
    psa_recent = _window_prices(psa_sales, current, max_age_days=recent_days)
    if min(len(target_old), len(psa_old), len(psa_recent)) < min_each:
        return None

    target_old_med = median(target_old)
    psa_old_med = median(psa_old)
    psa_recent_med = median(psa_recent)
    if min(target_old_med, psa_old_med, psa_recent_med) <= 0:
        return None
    ratio = target_old_med / psa_old_med
    if ratio < 0.35 or ratio > 1.50:
        return None

    psa_momentum = (psa_recent_med / psa_old_med - 1.0) * 100.0
    if psa_momentum < min_psa_momentum:
        return None
    implied = psa_recent_med * ratio
    current_gap = _pct_below(implied, lot.current_price)
    if current_gap < min_gap:
        return None

    target_recent = _window_prices(target_sales, current, max_age_days=recent_days)
    if len(target_recent) >= min_each and median(target_recent) >= implied * 0.90:
        return None

    return GraderLagSignal(
        grader,
        float(target_grade),
        round(ratio, 3),
        round(psa_old_med, 2),
        round(psa_recent_med, 2),
        round(psa_momentum, 1),
        round(implied, 2),
        round(current_gap, 1),
        len(target_old),
        len(psa_old),
        len(psa_recent),
    )


def liquidity_breakout_signal(
    candidate,
    now: Optional[datetime] = None,
) -> Optional[LiquidityBreakoutSignal]:
    current = _aware(now) or datetime.now(timezone.utc)
    recent_days = max(21, _env_int("V4_EDGE_LIQUIDITY_BREAKOUT_RECENT_DAYS", 45))
    baseline_days = max(recent_days + 90, _env_int("V4_EDGE_LIQUIDITY_BREAKOUT_BASELINE_DAYS", 365))
    min_recent = max(3, _env_int("V4_EDGE_LIQUIDITY_BREAKOUT_MIN_RECENT_SOLD", 3))
    max_prior = max(0, _env_int("V4_EDGE_LIQUIDITY_BREAKOUT_MAX_PRIOR_SOLD", 2))
    min_price_gap = _env_float("V4_EDGE_LIQUIDITY_BREAKOUT_MIN_PRICE_GAP_PCT", 15.0)
    min_price_move = _env_float("V4_EDGE_LIQUIDITY_BREAKOUT_MIN_PRICE_MOVE_PCT", 10.0)

    sales = _dated_exact_target_sales(candidate.lot, list(candidate.gcc.sales or []))
    recent = _window_prices(sales, current, max_age_days=recent_days)
    prior = _window_prices(
        sales, current, min_age_days=recent_days, max_age_days=baseline_days
    )
    if len(recent) < min_recent or len(prior) > max_prior:
        return None

    recent_med = median(recent)
    price_gap = _pct_below(recent_med, candidate.lot.current_price)
    if price_gap < min_price_gap:
        return None

    prior_med = median(prior) if prior else None
    move = None
    if prior_med is not None:
        if prior_med <= 0:
            return None
        move = (recent_med / prior_med - 1.0) * 100.0
        if move < min_price_move:
            return None

    return LiquidityBreakoutSignal(
        len(recent),
        len(prior),
        round(recent_med, 2),
        round(prior_med, 2) if prior_med is not None else None,
        round(price_gap, 1),
        round(move, 1) if move is not None else None,
    )


def relative_grade_anomaly_signal(
    candidate,
    now: Optional[datetime] = None,
) -> Optional[RelativeGradeAnomalySignal]:
    lot = candidate.lot
    target = _grade(lot)
    grader = (lot.grader or "").strip().upper()
    if target is None or not grader:
        return None

    current = _aware(now) or datetime.now(timezone.utc)
    max_days = max(90, _env_int("V4_EDGE_RELATIVE_GRADE_MAX_DAYS", 365))
    min_sales = max(2, _env_int("V4_EDGE_RELATIVE_GRADE_MIN_LOWER_SOLD", 2))
    min_inversion = _env_float("V4_EDGE_RELATIVE_GRADE_MIN_INVERSION_PCT", 10.0)

    by_grade: dict[float, list[watcher.ComparableSale]] = {}
    for sale in list(candidate.gcc.sales or []):
        if (
            not isinstance(sale, watcher.ComparableSale)
            or not sale.exact_card
            or sale.price <= 0
            or sale.sold_at is None
            or sale.grade_qualifier
            or (sale.grader or "").strip().upper() != grader
            or sale.grade is None
            or float(sale.grade) >= float(target)
        ):
            continue
        sold_at = _aware(sale.sold_at)
        if sold_at is None or sold_at > current:
            continue
        age = (current - sold_at).total_seconds() / 86400.0
        if age <= max_days:
            by_grade.setdefault(float(sale.grade), []).append(sale)

    eligible = {
        grade: sales for grade, sales in by_grade.items() if len(sales) >= min_sales
    }
    if not eligible:
        return None
    lower_grade = max(eligible)
    prices = [float(sale.price) for sale in eligible[lower_grade]]
    lower_med = median(prices)
    inversion = _pct_below(lower_med, lot.current_price)
    if inversion < min_inversion:
        return None
    return RelativeGradeAnomalySignal(
        float(target),
        lower_grade,
        round(lower_med, 2),
        len(prices),
        round(inversion, 1),
    )


def _strict_identity_key(lot: watcher.Lot) -> str:
    if not watcher.commercial_identity_is_sufficient(lot):
        return ""
    try:
        return watcher.external_commercial_identity_key(lot)
    except Exception:
        return ""


def same_card_inventory_signal(
    candidate,
    all_fixed_lots: list[watcher.Lot],
    now: Optional[datetime] = None,
) -> Optional[SameCardInventorySignal]:
    lot = candidate.lot
    key = _strict_identity_key(lot)
    if not key or lot.source_type != "fixed":
        return None

    exact = []
    for other in all_fixed_lots:
        if other.source_type != "fixed" or other.current_price is None:
            continue
        if _strict_identity_key(other) == key:
            exact.append(other)
    if len(exact) < 2:
        return None
    exact.sort(key=lambda item: float(item.current_price))
    if exact[0].url != lot.url:
        return None

    lowest = float(exact[0].current_price)
    next_ask = float(exact[1].current_price)
    if next_ask <= 0:
        return None
    inventory_gap = (next_ask - lowest) / next_ask * 100.0
    min_inventory_gap = _env_float("V4_EDGE_INVENTORY_MIN_GAP_PCT", 15.0)
    if inventory_gap < min_inventory_gap:
        return None

    current = _aware(now) or datetime.now(timezone.utc)
    recent_days = max(30, _env_int("V4_EDGE_INVENTORY_SOLD_DAYS", 90))
    min_sold = max(2, _env_int("V4_EDGE_INVENTORY_MIN_SOLD", 2))
    min_sold_gap = _env_float("V4_EDGE_INVENTORY_MIN_SOLD_GAP_PCT", 15.0)
    sales = _dated_exact_target_sales(lot, list(candidate.gcc.sales or []))
    sold_prices = _window_prices(sales, current, max_age_days=recent_days)
    if len(sold_prices) < min_sold:
        return None
    sold_med = median(sold_prices)
    sold_gap = _pct_below(sold_med, lowest)
    if sold_gap < min_sold_gap:
        return None

    return SameCardInventorySignal(
        round(lowest, 2),
        round(next_ask, 2),
        round(inventory_gap, 1),
        round(sold_med, 2),
        len(sold_prices),
        round(sold_gap, 1),
        len(exact),
    )


def stale_seller_repricing_signal(
    candidate,
    all_fixed_lots: list[watcher.Lot],
    now: Optional[datetime] = None,
) -> Optional[StaleSellerRepricingSignal]:
    seller = str(getattr(candidate.lot, "gcc_seller_key", "") or "")
    if not seller or candidate.lot.source_type != "fixed":
        return None
    momentum = roi.market_momentum_signal(candidate, now)
    if momentum is None or not momentum.actionable_edge:
        return None

    current = _aware(now) or datetime.now(timezone.utc)
    stale_days = max(7.0, _env_float("V4_EDGE_SELLER_STALE_DAYS", 14.0))
    seller_lots = [
        lot for lot in all_fixed_lots
        if str(getattr(lot, "gcc_seller_key", "") or "") == seller
    ]
    if len(seller_lots) < 2:
        return None
    stale_count = 0
    for lot in seller_lots:
        age = roi.listing_age_days(lot, current)
        if age is not None and age >= stale_days:
            stale_count += 1
    min_stale = max(2, _env_int("V4_EDGE_SELLER_MIN_STALE_LISTINGS", 2))
    if stale_count < min_stale:
        return None
    age = roi.listing_age_days(candidate.lot, current)
    if age is None:
        return None
    return StaleSellerRepricingSignal(
        seller,
        len(seller_lots),
        stale_count,
        round(age, 1),
        momentum.momentum_pct,
        momentum.price_gap_pct,
    )


def expected_profit_info(op: watcher.Opportunity) -> Optional[ExpectedProfitInfo]:
    """Informative net-edge estimate; never an alert gate."""
    try:
        price = float(op.lot.current_price)
        central = float(op.estimate.central)
        low = float(op.estimate.low)
    except (TypeError, ValueError, AttributeError):
        return None
    if min(price, central, low) <= 0:
        return None
    fee_pct = max(0.0, min(50.0, _env_float("V4_EDGE_EXPECTED_PROFIT_FEE_PCT", 0.0)))
    fixed_cost = max(0.0, _env_float("V4_EDGE_EXPECTED_PROFIT_FIXED_COST_EUR", 0.0))
    multiplier = 1.0 - fee_pct / 100.0
    central_net = central * multiplier - fixed_cost
    conservative_net = low * multiplier - fixed_cost
    central_profit = central_net - price
    conservative_profit = conservative_net - price
    return ExpectedProfitInfo(
        round(central_profit, 2),
        round(conservative_profit, 2),
        round(central_profit / price * 100.0, 1),
        round(conservative_profit / price * 100.0, 1),
        fee_pct,
        fixed_cost,
    )


def _candidate_signal_bonus(candidate, all_fixed_lots: list[watcher.Lot]) -> float:
    if candidate.lot.source_type == "auction":
        return 0.0
    bonus = 0.0
    if grader_lag_signal(candidate) is not None:
        bonus += 25.0
    if liquidity_breakout_signal(candidate) is not None:
        bonus += 20.0
    if relative_grade_anomaly_signal(candidate) is not None:
        bonus += 25.0
    if same_card_inventory_signal(candidate, all_fixed_lots) is not None:
        bonus += 25.0
    if stale_seller_repricing_signal(candidate, all_fixed_lots) is not None:
        bonus += 20.0
    return bonus


def _priority_score_with_structural_edges(candidate) -> float:
    base = float(_ORIGINAL_PRIORITY_SCORE(candidate))
    if candidate.lot.source_type == "auction":
        return base
    return round(base + _candidate_signal_bonus(candidate, list(_RUN_FIXED_LOTS.values())), 4)


def _process_with_structural_edges(
    page,
    candidates,
    state,
    budgets,
    diagnostics,
    run_now,
):
    opportunities = _ORIGINAL_PROCESS(
        page, candidates, state, budgets, diagnostics, run_now
    )
    by_url = {candidate.lot.url: candidate for candidate in candidates}
    all_fixed = list(_RUN_FIXED_LOTS.values())

    for op in opportunities:
        candidate = by_url.get(op.lot.url)
        if candidate is None:
            continue

        signals = []
        cross = cross_market_lag_signal(op, run_now)
        if cross is not None:
            setattr(op, "cross_market_lag_signal", cross)
            signals.append("CROSS_MARKET_LAG")

        grader = grader_lag_signal(candidate, run_now)
        if grader is not None:
            setattr(op, "grader_lag_signal", grader)
            signals.append("GRADER_LAG")

        liquidity = liquidity_breakout_signal(candidate, run_now)
        if liquidity is not None:
            setattr(op, "liquidity_breakout_signal", liquidity)
            signals.append("LIQUIDITY_BREAKOUT")

        relative = relative_grade_anomaly_signal(candidate, run_now)
        if relative is not None:
            setattr(op, "relative_grade_anomaly_signal", relative)
            signals.append("RELATIVE_GRADE_ANOMALY")

        inventory = same_card_inventory_signal(candidate, all_fixed, run_now)
        if inventory is not None:
            setattr(op, "same_card_inventory_signal", inventory)
            signals.append("SAME_CARD_INVENTORY_ANOMALY")

        seller = stale_seller_repricing_signal(candidate, all_fixed, run_now)
        if seller is not None:
            setattr(op, "stale_seller_repricing_signal", seller)
            signals.append("STALE_SELLER_REPRICING")

        profit = expected_profit_info(op)
        if profit is not None:
            setattr(op, "expected_profit_info", profit)

        if signals:
            watcher.log(
                f"Structural Edge Hunter: {','.join(signals)} | {op.lot.title}"
            )

    ranked = [
        op for op in opportunities
        if isinstance(getattr(op, "expected_profit_info", None), ExpectedProfitInfo)
    ]
    ranked.sort(
        key=lambda op: getattr(op, "expected_profit_info").central_profit_eur,
        reverse=True,
    )
    total = len(ranked)
    for rank, op in enumerate(ranked, start=1):
        info = getattr(op, "expected_profit_info")
        setattr(
            op,
            "expected_profit_info",
            ExpectedProfitInfo(
                info.central_profit_eur,
                info.conservative_profit_eur,
                info.central_roi_pct,
                info.conservative_roi_pct,
                info.assumed_fee_pct,
                info.assumed_fixed_cost_eur,
                rank,
                total,
            ),
        )
    return opportunities


def _fmt_pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:+.1f}%"


def _structural_block(op: watcher.Opportunity) -> str:
    blocks: list[str] = []

    signal = getattr(op, "cross_market_lag_signal", None)
    if isinstance(signal, CrossMarketLagSignal):
        src = "/".join(signal.sources) or "EXTERNE"
        blocks.append(
            "CROSS-MARKET LAG — SOLD EXACTS\n"
            f"{src} récent : {signal.external_recent_median:.2f} € "
            f"(n={signal.external_recent_count}) | GCC réf. : "
            f"{signal.gcc_reference_median:.2f} € (n={signal.gcc_reference_count})\n"
            f"Marché externe +{signal.market_lag_pct:.1f}% vs GCC | "
            f"prix GCC {signal.price_gap_pct:.1f}% sous externe récent\n"
            "SOLD exacts uniquement — Cardmarket RAW n'est pas traité comme une vente."
        )

    signal = getattr(op, "grader_lag_signal", None)
    if isinstance(signal, GraderLagSignal):
        blocks.append(
            "GRADER LAG — SPREAD HISTORIQUE PROUVÉ\n"
            f"PSA {signal.grade:g} : {signal.psa_baseline_median:.2f} → "
            f"{signal.psa_recent_median:.2f} € ({signal.psa_momentum_pct:+.1f}%)\n"
            f"Ratio historique {signal.target_grader}/PSA : "
            f"{signal.historical_target_per_psa_ratio:.3f} | "
            f"valeur implicite {signal.target_grader} : {signal.implied_target_value:.2f} €\n"
            f"Prix GCC {signal.current_gap_pct:.1f}% sous valeur implicite."
        )

    signal = getattr(op, "stale_seller_repricing_signal", None)
    if isinstance(signal, StaleSellerRepricingSignal):
        blocks.append(
            "STALE SELLER REPRICING\n"
            f"Vendeur explicite : {signal.active_fixed_count} annonces actives, "
            f"{signal.stale_fixed_count} anciennes | annonce {signal.listing_age_days:.1f} j\n"
            f"Momentum SOLD exact : +{signal.momentum_pct:.1f}% | "
            f"prix GCC {signal.price_gap_pct:.1f}% sous médiane récente."
        )

    signal = getattr(op, "liquidity_breakout_signal", None)
    if isinstance(signal, LiquidityBreakoutSignal):
        prior = (
            f"{signal.prior_median:.2f} €"
            if signal.prior_median is not None else "aucun prix de référence"
        )
        blocks.append(
            "LIQUIDITY BREAKOUT — SOLD EXACTS\n"
            f"Cluster récent : n={signal.recent_count}, médiane "
            f"{signal.recent_median:.2f} € | ancien historique : "
            f"n={signal.prior_count}, {prior}\n"
            f"Prix GCC {signal.price_gap_pct:.1f}% sous médiane récente"
            + (
                f" | hausse prix {signal.recent_vs_prior_pct:+.1f}%."
                if signal.recent_vs_prior_pct is not None else "."
            )
        )

    signal = getattr(op, "relative_grade_anomaly_signal", None)
    if isinstance(signal, RelativeGradeAnomalySignal):
        blocks.append(
            "RELATIVE-GRADE ANOMALY\n"
            f"{op.lot.grader} {signal.target_grade:g} affiché "
            f"{signal.inversion_pct:.1f}% sous la médiane SOLD du grade inférieur "
            f"{op.lot.grader} {signal.lower_grade:g} "
            f"({signal.lower_grade_median:.2f} €, n={signal.lower_grade_count})."
        )

    signal = getattr(op, "same_card_inventory_signal", None)
    if isinstance(signal, SameCardInventorySignal):
        ask = getattr(op, "exact_active_ask", None)
        ebay_line = ""
        if ask is not None and getattr(ask, "price", None):
            ebay_line = (
                f"\nASK eBay exact : {float(ask.price):.2f} € — ASK, PAS UNE VENTE."
            )
        blocks.append(
            "SAME-CARD INVENTORY ANOMALY\n"
            f"GCC exact : {signal.lowest_ask:.2f} € vs prochain ask "
            f"{signal.next_exact_ask:.2f} € ({signal.inventory_gap_pct:.1f}% plus bas), "
            f"n={signal.exact_active_count}\n"
            f"SOLD exacts récents : médiane {signal.recent_sold_median:.2f} € "
            f"(n={signal.recent_sold_count}) | GCC "
            f"{signal.sold_gap_pct:.1f}% sous SOLD"
            f"{ebay_line}"
        )

    profit = getattr(op, "expected_profit_info", None)
    if isinstance(profit, ExpectedProfitInfo):
        if profit.assumed_fee_pct == 0 and profit.assumed_fixed_cost_eur == 0:
            cost_note = "avant frais/coûts"
        else:
            cost_note = (
                f"hypothèse frais {profit.assumed_fee_pct:.1f}% + "
                f"{profit.assumed_fixed_cost_eur:.2f} €"
            )
        rank = (
            f" | rang informatif {profit.rank}/{profit.total_ranked}"
            if profit.rank and profit.total_ranked else ""
        )
        blocks.append(
            "EXPECTED PROFIT — INFORMATION SECONDAIRE, JAMAIS UN FILTRE\n"
            f"Central : {profit.central_profit_eur:+.2f} € "
            f"({_fmt_pct(profit.central_roi_pct)}) | prudent : "
            f"{profit.conservative_profit_eur:+.2f} € "
            f"({_fmt_pct(profit.conservative_roi_pct)})\n"
            f"{cost_note}{rank}. Une forte décote reste notifiée indépendamment de ce chiffre."
        )

    if not blocks:
        return ""
    return "STRUCTURAL EDGE HUNTER\n\n" + "\n\n".join(blocks)


def _inject_before_listing_url(data: object, block: str, listing_url: str) -> object:
    if not block:
        return data
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return data
        rewritten = _inject_before_listing_url(text, block, listing_url)
        return rewritten.encode("utf-8") if isinstance(rewritten, str) else data
    if not isinstance(data, str):
        return data
    marker = listing_url if listing_url and listing_url in data else ""
    if marker:
        return data.replace(marker, block + "\n\n" + marker, 1)
    return data.rstrip() + "\n\n" + block


def _notify_with_structural_edges(
    op: watcher.Opportunity,
    decision: watcher.NotificationDecision,
) -> None:
    block = _structural_block(op)
    if not block or not watcher.NTFY_TOPIC:
        return _ORIGINAL_NOTIFY(op, decision)
    original_post = watcher.requests.post

    def post_with_edges(url, *args, **kwargs):
        kwargs["data"] = _inject_before_listing_url(
            kwargs.get("data"), block, op.lot.url
        )
        return original_post(url, *args, **kwargs)

    watcher.requests.post = post_with_edges
    try:
        return _ORIGINAL_NOTIFY(op, decision)
    finally:
        watcher.requests.post = original_post


def install_v4_structural_edge_hunter() -> None:
    global _ORIGINAL_FIXED_RESULT_TO_LOT, _ORIGINAL_PROCESS, _ORIGINAL_NOTIFY
    global _ORIGINAL_PRIORITY_SCORE, _INSTALLED
    if _INSTALLED:
        return

    _RUN_FIXED_LOTS.clear()
    _ORIGINAL_FIXED_RESULT_TO_LOT = watcher._gcc_fixed_result_to_lot
    _ORIGINAL_PROCESS = watcher.process_external_market_candidates
    _ORIGINAL_NOTIFY = watcher.notify
    _ORIGINAL_PRIORITY_SCORE = smart_priority.external_priority_score

    watcher._gcc_fixed_result_to_lot = _fixed_result_with_edge_metadata
    watcher.process_external_market_candidates = _process_with_structural_edges
    watcher.notify = _notify_with_structural_edges
    smart_priority.external_priority_score = _priority_score_with_structural_edges
    _INSTALLED = True

    watcher.log(
        "Structural Edge Hunter V2 enabled: cross-market/grader/seller/liquidity/"
        "relative-grade/inventory signals + expected-profit info; "
        "no opportunity suppression, no FV/max changes, asks never SOLD"
    )
