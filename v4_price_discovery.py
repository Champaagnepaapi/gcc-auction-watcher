"""
v4_price_discovery.py - Grader spread & asymmetric price discovery signals for GCC V4.

Provides deterministic evaluation of:
1. CROSSGRADE_OPPORTUNITY: Pristine secondary-grader slabs (PCA 10, BGS 9.5, CGC 10) with major PSA spread.
2. SECONDARY_GRADER_DISCOUNT: Liquid secondary-grader market at significant discount vs fair market value.
3. ILLIQUID_PRICE_DISCOVERY: Sparse exact grader/grade liquidity with multiple credible adjacent anchors
   strongly supporting asymmetric upside.

Core principles:
- LOW_LIQUIDITY is an uncertainty characteristic, NOT an automatic rejection.
- Sparse exact evidence may still produce a manual-review opportunity when multiple credible adjacent
  anchors strongly support asymmetric upside.
- Crossgrade probability is OPTIONAL evidence and must NOT be required.
- Stale active asks alone must NEVER create an opportunity.
- Incompatible dimensions (language, set, number, finish, promo) are strictly rejected or downweighted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence


CATEGORY_CROSSGRADE_OPPORTUNITY = "CROSSGRADE_OPPORTUNITY"
CATEGORY_SECONDARY_GRADER_DISCOUNT = "SECONDARY_GRADER_DISCOUNT"
CATEGORY_ILLIQUID_PRICE_DISCOVERY = "ILLIQUID_PRICE_DISCOVERY"

LIQUIDITY_LOW = "LOW"
LIQUIDITY_MODERATE = "MODERATE"
LIQUIDITY_HIGH = "HIGH"

EVIDENCE_QUALITY_LOW = "LOW"
EVIDENCE_QUALITY_MODERATE = "MODERATE"
EVIDENCE_QUALITY_STRONG = "STRONG"

UNCERTAINTY_LOW = "LOW"
UNCERTAINTY_MODERATE = "MODERATE"
UNCERTAINTY_HIGH = "HIGH"
UNCERTAINTY_VERY_HIGH = "VERY_HIGH"

GRADER_SPREAD_LOW = "LOW"
GRADER_SPREAD_MODERATE = "MODERATE"
GRADER_SPREAD_HIGH = "HIGH"
GRADER_SPREAD_VERY_HIGH = "VERY_HIGH"

EVIDENCE_LEVEL_EXACT_RECENT = "EXACT_RECENT_COMP"
EVIDENCE_LEVEL_TEMPORALLY_ADJUSTED = "EXACT_OLD_COMP_TEMPORALLY_ADJUSTED"
EVIDENCE_LEVEL_CROSS_GRADER_ONLY = "CROSS_GRADER_ESTIMATE_ONLY"
EVIDENCE_LEVEL_MANUAL_REVIEW_NO_ESTIMATE = "MANUAL_REVIEW_NO_ESTIMATE"

EXTRAPOLATION_TEMPORAL_CROSS_GRADER = "TEMPORAL_CROSS_GRADER_ADJUSTMENT"


@dataclass(frozen=True)
class HistoricalRatioObservation:
    """Historical sale of target grader with matched reference grader benchmark."""
    target_grader_price: float
    reference_grader_price: float
    ratio: float  # target_grader_price / reference_grader_price
    sold_at: Optional[Any] = None
    age_days: Optional[int] = None
    target_grader: str = ""
    reference_grader: str = "PSA"
    grade: str = ""
    language: str = "fr"
    reference_language: str = "fr"
    is_outlier: bool = False
    weight: float = 1.0


@dataclass(frozen=True)
class TemporalAdjustmentResult:
    """Detailed output of temporal cross-grader adjustment."""
    applied: bool = False
    historical_exact_grader_sale: Optional[float] = None
    historical_reference_price: Optional[float] = None
    historical_grader_reference_ratio: Optional[float] = None
    current_robust_reference_value: Optional[float] = None
    temporally_adjusted_low: Optional[float] = None
    temporally_adjusted_central: Optional[float] = None
    temporally_adjusted_high: Optional[float] = None
    implicit_discount_pct: Optional[float] = None
    is_extrapolated: bool = False
    extrapolation_type: Optional[str] = None
    evidence_level: str = EVIDENCE_LEVEL_MANUAL_REVIEW_NO_ESTIMATE
    observations_count: int = 0
    uncertainty: str = UNCERTAINTY_HIGH
    confidence: str = EVIDENCE_QUALITY_MODERATE
    uncertainty_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdjacentAnchor:
    """An adjacent market evidence anchor (e.g. PSA 10 sold, RAW consensus, GCC history)."""
    anchor_type: str  # "PSA_SAME_GRADE", "PSA_HIGHER_GRADE", "PCA_SOLD", "RAW_CONSENSUS", "GCC_HISTORY", "NEIGHBORING_GRADE", "BGS_CGC_SAME_GRADE", "ACTIVE_ASK"
    source: str       # "poketrace", "cardmarket", "justtcg", "tcgplayer", "ebay", "gcc"
    grader: Optional[str]
    grade: Optional[str]
    language: str     # "fr", "en", "ja", etc.
    price: float      # in EUR
    price_type: str = "SOLD"  # "SOLD", "CONSENSUS", "ASK"
    sale_count: int = 1
    is_active_ask: bool = False
    weight: float = 1.0
    age_days: Optional[int] = None
    is_recent: bool = True
    uncertainty_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class PriceDiscoverySignal:
    """Structured signal for grader spread and price discovery."""
    listing_identity: str
    gcc_price: float
    grader: str
    grade: str
    exact_grader_liquidity: str
    category: str
    liquidity: str
    evidence_quality: str
    uncertainty: str
    grader_spread: str
    credible_high_reference: float
    asymmetric_upside_ratio: float
    main_thesis: str
    credible_adjacent_anchors: tuple[AdjacentAnchor, ...]
    crossgrade_required: bool = False
    manual_review_recommended: bool = True
    diagnostics: tuple[str, ...] = ()
    # Temporal Cross Grader Adjustment fields
    historical_exact_grader_sale: Optional[float] = None
    historical_reference_price: Optional[float] = None
    historical_grader_reference_ratio: Optional[float] = None
    current_robust_reference_value: Optional[float] = None
    temporally_adjusted_low: Optional[float] = None
    temporally_adjusted_central: Optional[float] = None
    temporally_adjusted_high: Optional[float] = None
    implicit_discount_pct: Optional[float] = None
    is_extrapolated: bool = False
    extrapolation_type: Optional[str] = None
    evidence_level: str = EVIDENCE_LEVEL_MANUAL_REVIEW_NO_ESTIMATE


def _numeric_grade(raw_grade: object) -> Optional[float]:
    if raw_grade is None:
        return None
    try:
        return float(str(raw_grade).strip())
    except (ValueError, TypeError):
        return None


def compute_robust_reference_value(prices: Sequence[float]) -> Optional[float]:
    """Compute robust reference value avoiding single-outlier distortions."""
    valid_prices = sorted([float(p) for p in prices if p is not None and float(p) > 0])
    if not valid_prices:
        return None
    if len(valid_prices) == 1:
        return round(valid_prices[0], 2)
    if len(valid_prices) == 2:
        return round(sum(valid_prices) / 2.0, 2)

    # 3 or more: filter extreme outliers outside [0.4 * med, 2.0 * med]
    med = valid_prices[len(valid_prices) // 2]
    clean_prices = [p for p in valid_prices if 0.4 * med <= p <= 2.0 * med]
    if not clean_prices:
        clean_prices = [med]

    mid = len(clean_prices) // 2
    if len(clean_prices) % 2 == 1:
        robust_val = clean_prices[mid]
    else:
        robust_val = (clean_prices[mid - 1] + clean_prices[mid]) / 2.0
    return round(robust_val, 2)


def pair_date_matched_historical_ratios(
    stale_target_sales: Sequence[Any],
    historical_reference_sales: Sequence[Any],
    *,
    target_grader: str,
    target_grade: str,
    reference_grader: str = "PSA",
    target_language: str = "fr",
    max_delta_days: int = 90,
    now: Optional[Any] = None,
) -> list[HistoricalRatioObservation]:
    """
    Pair stale target-grader sales with date-matched same-grade reference-grader sales.
    Do NOT pair with current prices to compute historical ratio.
    """
    observations: list[HistoricalRatioObservation] = []
    norm_tg = (target_grader or "").strip().upper()
    num_grade = _numeric_grade(target_grade)
    norm_ref_grader = (reference_grader or "PSA").strip().upper()
    norm_t_lang = (target_language or "fr").strip().lower()

    # Filter reference sales to same grade and reference grader
    valid_ref_sales = []
    for r in historical_reference_sales:
        r_grader = (getattr(r, "grader", None) or "").strip().upper()
        r_grade = _numeric_grade(getattr(r, "grade", None))
        r_price = float(getattr(r, "price", 0) or 0)
        if (
            r_grader == norm_ref_grader
            and r_grade == num_grade
            and r_price > 0
        ):
            valid_ref_sales.append(r)

    if not valid_ref_sales:
        return []

    for t_comp in stale_target_sales:
        t_price = float(getattr(t_comp, "price", 0) or 0)
        t_sold_at = getattr(t_comp, "sold_at", None)
        t_age = getattr(t_comp, "age_days", None)
        if t_sold_at is not None and now is not None:
            try:
                t_age = max(0, int((now - t_sold_at).total_seconds() / 86400.0))
            except Exception:
                pass
        if t_age is None:
            t_age = 180

        if t_price <= 0:
            continue

        # Find reference sales close to t_sold_at or matching age
        matched_refs: list[tuple[float, float, Any]] = []
        for r_comp in valid_ref_sales:
            r_price = float(getattr(r_comp, "price", 0) or 0)
            r_sold_at = getattr(r_comp, "sold_at", None)
            r_age = getattr(r_comp, "age_days", None)
            if r_sold_at is not None and now is not None:
                try:
                    r_age = max(0, int((now - r_sold_at).total_seconds() / 86400.0))
                except Exception:
                    pass

            # Check date closeness
            if t_sold_at is not None and r_sold_at is not None:
                try:
                    delta = abs((t_sold_at - r_sold_at).total_seconds()) / 86400.0
                    if delta <= max_delta_days:
                        matched_refs.append((delta, r_price, r_comp))
                except Exception:
                    pass
            elif t_age is not None and r_age is not None:
                delta = abs(float(t_age) - float(r_age))
                if delta <= max_delta_days:
                    matched_refs.append((delta, r_price, r_comp))

        if matched_refs:
            matched_refs.sort(key=lambda x: x[0])
            ref_prices = [m[1] for m in matched_refs]
            r_price_matched = compute_robust_reference_value(ref_prices)
            if r_price_matched and r_price_matched > 0:
                best_ref = matched_refs[0][2]
                r_lang = getattr(best_ref, "context", None) or getattr(best_ref, "language", None) or norm_t_lang
                observations.append(
                    HistoricalRatioObservation(
                        target_grader_price=round(t_price, 2),
                        reference_grader_price=round(r_price_matched, 2),
                        ratio=round(t_price / r_price_matched, 4),
                        sold_at=t_sold_at,
                        age_days=t_age,
                        target_grader=norm_tg,
                        reference_grader=norm_ref_grader,
                        grade=str(target_grade),
                        language=norm_t_lang,
                        reference_language=str(r_lang).lower(),
                    )
                )

    return observations


def evaluate_temporal_cross_grader_adjustment(
    *,
    target_grader: str,
    target_grade: str,
    gcc_price: float,
    historical_target_sales: Sequence[Any] = (),
    historical_reference_sales: Sequence[Any] = (),
    current_robust_reference_value: Optional[float] = None,
    reference_grader: str = "PSA",
    target_language: str = "fr",
    reference_language: str = "fr",
    reference_volatility: str = "LOW",
    recent_exact_sales: Sequence[Any] = (),
    reference_is_recent: bool = True,
    now: Optional[Any] = None,
) -> TemporalAdjustmentResult:
    """
    Compute TEMPORAL_CROSS_GRADER_ADJUSTMENT:
    Rebase old exact secondary-grader sales using historical target/reference ratios
    and current robust reference-grader appreciation.
    """
    norm_target_grader = (target_grader or "").strip().upper()
    norm_ref_grader = (reference_grader or "PSA").strip().upper()
    norm_target_lang = (target_language or "fr").strip().lower()
    norm_ref_lang = (reference_language or "fr").strip().lower()

    if not reference_is_recent:
        return TemporalAdjustmentResult(
            applied=False,
            is_extrapolated=False,
            evidence_level=EVIDENCE_LEVEL_MANUAL_REVIEW_NO_ESTIMATE,
            uncertainty=UNCERTAINTY_VERY_HIGH,
            confidence=EVIDENCE_QUALITY_LOW,
            uncertainty_reasons=("NO_RECENT_REFERENCE_BENCHMARK",),
        )

    # 1. Check if recent exact sales exist (within 90 days)
    if recent_exact_sales:
        recent_prices = [
            float(getattr(s, "price", s) or 0) for s in recent_exact_sales
            if (getattr(s, "price", s) or 0) > 0
        ]
        if recent_prices:
            recent_avg = sum(recent_prices) / len(recent_prices)
            discount = ((recent_avg - gcc_price) / recent_avg * 100) if recent_avg > 0 else 0.0
            return TemporalAdjustmentResult(
                applied=False,
                historical_exact_grader_sale=round(recent_avg, 2),
                current_robust_reference_value=current_robust_reference_value,
                implicit_discount_pct=round(discount, 1),
                is_extrapolated=False,
                evidence_level=EVIDENCE_LEVEL_EXACT_RECENT,
                observations_count=len(recent_prices),
                uncertainty=UNCERTAINTY_LOW if len(recent_prices) >= 3 else UNCERTAINTY_MODERATE,
                confidence=EVIDENCE_QUALITY_STRONG if len(recent_prices) >= 3 else EVIDENCE_QUALITY_MODERATE,
                uncertainty_reasons=("RECENT_EXACT_SALES_AVAILABLE",),
            )

    # 2. Extract and pair historical observations
    observations: list[HistoricalRatioObservation] = []

    # If already HistoricalRatioObservation or tuples
    for item in historical_target_sales:
        if isinstance(item, HistoricalRatioObservation):
            observations.append(item)
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            t_price = float(item[0])
            r_price = float(item[1])
            age = int(item[2]) if len(item) > 2 else 180
            if t_price > 0 and r_price > 0:
                observations.append(
                    HistoricalRatioObservation(
                        target_grader_price=t_price,
                        reference_grader_price=r_price,
                        ratio=round(t_price / r_price, 4),
                        age_days=age,
                        target_grader=norm_target_grader,
                        reference_grader=norm_ref_grader,
                        grade=str(target_grade),
                        language=norm_target_lang,
                        reference_language=norm_ref_lang,
                    )
                )

    # If raw target comps + raw reference comps are passed
    if not observations and historical_target_sales and historical_reference_sales:
        observations = pair_date_matched_historical_ratios(
            historical_target_sales,
            historical_reference_sales,
            target_grader=norm_target_grader,
            target_grade=str(target_grade),
            reference_grader=norm_ref_grader,
            target_language=norm_target_lang,
            now=now,
        )

    if not observations or not current_robust_reference_value or current_robust_reference_value <= 0:
        return TemporalAdjustmentResult(
            applied=False,
            is_extrapolated=False,
            evidence_level=EVIDENCE_LEVEL_MANUAL_REVIEW_NO_ESTIMATE,
            uncertainty=UNCERTAINTY_VERY_HIGH,
            confidence=EVIDENCE_QUALITY_LOW,
            uncertainty_reasons=("NO_USABLE_HISTORICAL_RATIO_OR_REFERENCE",),
        )

    # 3. Robust median / outlier rejection on historical ratios
    ratios = [obs.ratio for obs in observations if obs.ratio > 0]
    if not ratios:
        return TemporalAdjustmentResult(
            applied=False,
            is_extrapolated=False,
            evidence_level=EVIDENCE_LEVEL_MANUAL_REVIEW_NO_ESTIMATE,
            uncertainty=UNCERTAINTY_VERY_HIGH,
            confidence=EVIDENCE_QUALITY_LOW,
            uncertainty_reasons=("INVALID_RATIOS",),
        )

    # Outlier filter if >= 3 observations
    sorted_ratios = sorted(ratios)
    if len(sorted_ratios) >= 3:
        median_idx = len(sorted_ratios) // 2
        med = sorted_ratios[median_idx]
        # Keep ratios within [0.4 * med, 2.0 * med]
        clean_ratios = [r for r in sorted_ratios if 0.4 * med <= r <= 2.0 * med]
        if not clean_ratios:
            clean_ratios = [med]
    else:
        clean_ratios = sorted_ratios

    # Compute robust median ratio
    mid = len(clean_ratios) // 2
    if len(clean_ratios) % 2 == 1:
        robust_ratio = clean_ratios[mid]
    else:
        robust_ratio = (clean_ratios[mid - 1] + clean_ratios[mid]) / 2.0

    # 4. Estimate current target-grader value
    curr_ref = float(current_robust_reference_value)
    adjusted_central = round(curr_ref * robust_ratio, 2)
    adjusted_low = round(adjusted_central * 0.85, 2)
    adjusted_high = round(adjusted_central * 1.15, 2)

    implicit_discount = round(((adjusted_central - gcc_price) / max(0.01, adjusted_central)) * 100, 1)

    # Representative historical observation
    rep_obs = observations[0]
    hist_target_sale = round(rep_obs.target_grader_price, 2)
    hist_ref_price = round(rep_obs.reference_grader_price, 2)

    # 5. Calculate uncertainty and confidence
    uncertainty_score = 0
    reasons: list[str] = []

    if len(observations) == 1:
        uncertainty_score += 1
        reasons.append("SINGLE_HISTORICAL_RATIO_OBSERVATION")

    max_age = max((obs.age_days or 180) for obs in observations)
    if max_age > 180:
        uncertainty_score += 1
        reasons.append(f"STALE_TARGET_GRADER_SALE_{max_age}D")

    if norm_target_lang != norm_ref_lang:
        uncertainty_score += 1
        reasons.append(f"CROSS_LANGUAGE_BENCHMARK_{norm_target_lang.upper()}_VS_{norm_ref_lang.upper()}")

    if reference_volatility.upper() in {"MODERATE", "HIGH"}:
        uncertainty_score += 1
        reasons.append(f"REFERENCE_MARKET_VOLATILITY_{reference_volatility.upper()}")

    if norm_target_grader not in {"PSA", "BGS", "CGC"}:
        uncertainty_score += 1
        reasons.append(f"SECONDARY_GRADER_{norm_target_grader}")

    if uncertainty_score >= 3:
        uncertainty = UNCERTAINTY_HIGH if uncertainty_score == 3 else UNCERTAINTY_VERY_HIGH
        confidence = EVIDENCE_QUALITY_LOW if uncertainty_score >= 4 else EVIDENCE_QUALITY_MODERATE
    elif uncertainty_score == 2:
        uncertainty = UNCERTAINTY_HIGH
        confidence = EVIDENCE_QUALITY_MODERATE
    elif uncertainty_score == 1:
        uncertainty = UNCERTAINTY_MODERATE
        confidence = EVIDENCE_QUALITY_MODERATE
    else:
        uncertainty = UNCERTAINTY_LOW
        confidence = EVIDENCE_QUALITY_STRONG

    return TemporalAdjustmentResult(
        applied=True,
        historical_exact_grader_sale=hist_target_sale,
        historical_reference_price=hist_ref_price,
        historical_grader_reference_ratio=round(robust_ratio, 4),
        current_robust_reference_value=round(curr_ref, 2),
        temporally_adjusted_low=adjusted_low,
        temporally_adjusted_central=adjusted_central,
        temporally_adjusted_high=adjusted_high,
        implicit_discount_pct=implicit_discount,
        is_extrapolated=True,
        extrapolation_type=EXTRAPOLATION_TEMPORAL_CROSS_GRADER,
        evidence_level=EVIDENCE_LEVEL_TEMPORALLY_ADJUSTED,
        observations_count=len(observations),
        uncertainty=uncertainty,
        confidence=confidence,
        uncertainty_reasons=tuple(reasons),
    )



def evaluate_price_discovery(
    *,
    listing_identity: str,
    gcc_price: float,
    grader: str,
    grade: str,
    language: str = "fr",
    target_language: Optional[str] = None,
    exact_grader_sales: Sequence[Any] = (),
    recent_exact_sales: Sequence[Any] = (),
    adjacent_anchors: Sequence[AdjacentAnchor] = (),
    raw_consensus: Optional[Any] = None,
    crossgrade_probability: Optional[float] = None,
    temporal_adjustment: Optional[TemporalAdjustmentResult] = None,
    historical_target_sales: Sequence[Any] = (),
    historical_reference_sales: Sequence[Any] = (),
    now: Optional[datetime] = None,
) -> PriceDiscoverySignal:
    """
    Evaluate grader spread and price discovery for a listing using credible adjacent evidence.
    """
    norm_grader = (grader or "").strip().upper()
    norm_grade = (grade or "").strip()
    num_grade = _numeric_grade(norm_grade)
    norm_lang = (target_language or language or "fr").strip().lower()

    # Determine actual recent exact sales (<= 90 days) matching exact grader and grade
    filtered_recent_sales: list[Any] = list(recent_exact_sales)
    if not filtered_recent_sales and exact_grader_sales:
        for s in exact_grader_sales:
            s_grader = getattr(s, "grader", None)
            if s_grader is not None and str(s_grader or "").strip().upper() != norm_grader:
                continue
            s_grade = getattr(s, "grade", None)
            if s_grade is not None and _numeric_grade(s_grade) != num_grade:
                continue

            s_sold_at = getattr(s, "sold_at", None)
            s_age = getattr(s, "age_days", None)
            if s_sold_at is not None and now is not None:
                try:
                    if (now - s_sold_at).total_seconds() <= 90 * 86400:
                        filtered_recent_sales.append(s)
                except Exception:
                    pass
            elif s_age is not None:
                if s_age <= 90:
                    filtered_recent_sales.append(s)
            elif not hasattr(s, "sold_at") and not hasattr(s, "age_days"):
                filtered_recent_sales.append(s)



    # If temporal adjustment is not precomputed but historical sales are supplied, compute it
    if temporal_adjustment is None and historical_target_sales:
        # Find current PSA / reference value from adjacent anchors robustly (strictly same grade and recent <= 90d)
        ref_anchors = [
            a for a in adjacent_anchors
            if (a.grader or "").upper() in {"PSA", "BGS", "CGC"}
            and _numeric_grade(a.grade) == num_grade
            and a.price_type == "SOLD"
            and not a.is_active_ask
            and (a.age_days is None or a.age_days <= 90)
            and getattr(a, "is_recent", True)
        ]
        ref_prices = [a.price for a in ref_anchors]
        curr_ref = compute_robust_reference_value(ref_prices)
        if curr_ref and curr_ref > 0:
            temporal_adjustment = evaluate_temporal_cross_grader_adjustment(
                target_grader=norm_grader,
                target_grade=norm_grade,
                gcc_price=gcc_price,
                historical_target_sales=historical_target_sales,
                historical_reference_sales=historical_reference_sales,
                current_robust_reference_value=curr_ref,
                target_language=norm_lang,
                recent_exact_sales=filtered_recent_sales,
                reference_is_recent=True,
                now=now,
            )
        else:
            temporal_adjustment = TemporalAdjustmentResult(
                applied=False,
                is_extrapolated=False,
                evidence_level=EVIDENCE_LEVEL_MANUAL_REVIEW_NO_ESTIMATE,
                uncertainty=UNCERTAINTY_VERY_HIGH,
                confidence=EVIDENCE_QUALITY_LOW,
                uncertainty_reasons=("NO_RECENT_REFERENCE_BENCHMARK",),
            )




    recent_sales_count = len(filtered_recent_sales)
    if recent_sales_count == 0:
        exact_grader_liquidity = LIQUIDITY_LOW
    elif recent_sales_count < 4:
        exact_grader_liquidity = LIQUIDITY_MODERATE
    else:
        exact_grader_liquidity = LIQUIDITY_HIGH

    # 1. Process and filter adjacent anchors
    credible_anchors: list[AdjacentAnchor] = []
    has_active_ask_only = True

    # If temporal adjustment is applied, inject the temporally adjusted estimate anchor
    if temporal_adjustment is not None and temporal_adjustment.applied and temporal_adjustment.temporally_adjusted_central:
        credible_anchors.append(
            AdjacentAnchor(
                anchor_type="TEMPORALLY_ADJUSTED_ESTIMATE",
                source="temporal_cross_grader",
                grader=norm_grader,
                grade=norm_grade,
                language=norm_lang,
                price=temporal_adjustment.temporally_adjusted_central,
                price_type="ADJUSTED_ESTIMATE",
                sale_count=temporal_adjustment.observations_count or 1,
                weight=1.0,
                uncertainty_reasons=temporal_adjustment.uncertainty_reasons,
            )
        )
        has_active_ask_only = False

    for anchor in adjacent_anchors:
        reasons = list(anchor.uncertainty_reasons)
        weight = float(anchor.weight)

        # Stale active ask cannot create a strong opportunity alone
        if anchor.is_active_ask or anchor.price_type == "ASK":
            weight *= 0.15
            reasons.append("ACTIVE_ASK_DOWNWEIGHTED")
        else:
            has_active_ask_only = False

        # Language mismatch downweighting
        anchor_lang = (anchor.language or "").strip().lower()
        if anchor_lang and norm_lang and anchor_lang != norm_lang:
            weight *= 0.50
            reasons.append(f"LANGUAGE_DIFFERENCE_{anchor_lang.upper()}_VS_{norm_lang.upper()}")

        # Low-grade penalty: If listing is <= 7.0 (e.g. CA 6), PSA 10 anchor does not prove grade 6 value
        anchor_grade = _numeric_grade(anchor.grade)
        if num_grade is not None and anchor_grade is not None:
            if num_grade <= 7.0 and anchor_grade >= 9.5:
                # Discard wide grade gap anchor for low-grade listing
                continue
            elif num_grade < anchor_grade:
                weight *= 0.65
                reasons.append(f"HIGHER_GRADE_ANCHOR_{anchor_grade}_VS_{num_grade}")

        if anchor.price > 0 and weight > 0:
            credible_anchors.append(
                AdjacentAnchor(
                    anchor_type=anchor.anchor_type,
                    source=anchor.source,
                    grader=anchor.grader,
                    grade=anchor.grade,
                    language=anchor.language,
                    price=anchor.price,
                    price_type=anchor.price_type,
                    sale_count=anchor.sale_count,
                    is_active_ask=anchor.is_active_ask,
                    weight=weight,
                    uncertainty_reasons=tuple(reasons),
                )
            )

    # 2. Determine credible high reference from solid anchors (PSA, RAW, high sold comps)
    sold_anchors = [a for a in credible_anchors if not a.is_active_ask and a.price_type != "ASK"]

    if not sold_anchors:

        # Negative regression: sparse market with only stale active asks or no anchors
        return PriceDiscoverySignal(
            listing_identity=listing_identity,
            gcc_price=gcc_price,
            grader=norm_grader,
            grade=norm_grade,
            exact_grader_liquidity=exact_grader_liquidity,
            category=CATEGORY_ILLIQUID_PRICE_DISCOVERY,
            liquidity=LIQUIDITY_LOW,
            evidence_quality=EVIDENCE_QUALITY_LOW,
            uncertainty=UNCERTAINTY_VERY_HIGH,
            grader_spread=GRADER_SPREAD_LOW,
            credible_high_reference=0.0,
            asymmetric_upside_ratio=1.0,
            main_thesis="No credible sold or consensus adjacent anchors found",
            credible_adjacent_anchors=tuple(credible_anchors),
            crossgrade_required=False,
            manual_review_recommended=False,
            diagnostics=("REJECTED_NO_SOLID_ANCHORS",),
        )

    # Calculate credible high reference (weighted average of solid anchors)
    total_weight = sum(a.weight for a in sold_anchors)
    weighted_price = sum(a.price * a.weight for a in sold_anchors) / max(0.001, total_weight)
    credible_high_ref = round(weighted_price, 2)

    # If PSA strict same-grade sold anchor exists, compute robust benchmark with haircuts applied
    psa_anchors = [
        a for a in sold_anchors
        if (a.grader or "").upper() == "PSA" and _numeric_grade(a.grade) == num_grade
    ]
    if psa_anchors:
        effective_psa_prices = [a.price * a.weight for a in psa_anchors if a.price > 0 and a.weight > 0]
        if effective_psa_prices:
            robust_psa_val = compute_robust_reference_value(effective_psa_prices)
            if robust_psa_val and robust_psa_val > 0:
                credible_high_ref = round(robust_psa_val, 2)

    upside_ratio = round(credible_high_ref / max(0.01, gcc_price), 2) if gcc_price > 0 else 1.0

    # 3. Calculate Grader Spread
    if psa_anchors:
        effective_psa_prices = [a.price * a.weight for a in psa_anchors if a.price > 0 and a.weight > 0]
        psa_ref = compute_robust_reference_value(effective_psa_prices) or credible_high_ref
        ratio_to_psa = psa_ref / max(0.01, gcc_price)
        if ratio_to_psa >= 3.0:
            grader_spread = GRADER_SPREAD_VERY_HIGH
        elif ratio_to_psa >= 1.8:
            grader_spread = GRADER_SPREAD_HIGH
        elif ratio_to_psa >= 1.25:
            grader_spread = GRADER_SPREAD_MODERATE
        else:
            grader_spread = GRADER_SPREAD_LOW
    else:
        if upside_ratio >= 3.0:
            grader_spread = GRADER_SPREAD_VERY_HIGH
        elif upside_ratio >= 1.8:
            grader_spread = GRADER_SPREAD_HIGH
        elif upside_ratio >= 1.25:
            grader_spread = GRADER_SPREAD_MODERATE
        else:
            grader_spread = GRADER_SPREAD_LOW

    # 4. Uncertainty & Evidence Quality
    # LOW_LIQUIDITY is an uncertainty characteristic, NOT an automatic rejection
    uncertainty_score = 0
    if exact_grader_liquidity == LIQUIDITY_LOW:
        uncertainty_score += 2
    elif exact_grader_liquidity == LIQUIDITY_MODERATE:
        uncertainty_score += 1

    if any("LANGUAGE_DIFFERENCE" in r for a in credible_anchors for r in a.uncertainty_reasons):
        uncertainty_score += 1

    if norm_grader not in {"PSA", "BGS", "CGC"}:
        uncertainty_score += 1

    if temporal_adjustment is not None and temporal_adjustment.applied:
        if temporal_adjustment.uncertainty == UNCERTAINTY_HIGH:
            uncertainty_score += 1
        elif temporal_adjustment.uncertainty == UNCERTAINTY_VERY_HIGH:
            uncertainty_score += 2

    if uncertainty_score >= 3:
        uncertainty = UNCERTAINTY_HIGH if uncertainty_score == 3 else UNCERTAINTY_VERY_HIGH
    elif uncertainty_score == 2:
        uncertainty = UNCERTAINTY_HIGH
    elif uncertainty_score == 1:
        uncertainty = UNCERTAINTY_MODERATE
    else:
        uncertainty = UNCERTAINTY_LOW

    # Evidence Quality based on distinct sources and sold counts
    distinct_sources = {a.source for a in sold_anchors}
    total_sales = sum(a.sale_count for a in sold_anchors)
    if exact_grader_liquidity == LIQUIDITY_LOW:
        # Sparse exact liquidity caps evidence quality at MODERATE
        if len(distinct_sources) >= 1 and total_sales >= 2:
            evidence_quality = EVIDENCE_QUALITY_MODERATE
        else:
            evidence_quality = EVIDENCE_QUALITY_LOW
    else:
        if len(distinct_sources) >= 2 and total_sales >= 4:
            evidence_quality = EVIDENCE_QUALITY_STRONG
        elif len(distinct_sources) >= 1 and total_sales >= 2:
            evidence_quality = EVIDENCE_QUALITY_MODERATE
        else:
            evidence_quality = EVIDENCE_QUALITY_LOW

    # Check if ONLY cross-language or wide-grade anchors exist without same-language / raw support
    has_same_lang_or_raw = any(
        (a.language == norm_lang and not any("LANGUAGE_DIFFERENCE" in r for r in a.uncertainty_reasons))
        or a.anchor_type in {"RAW_CONSENSUS", "EXACT_GCC_SOLD", "TEMPORALLY_ADJUSTED_ESTIMATE"}
        for a in sold_anchors
    )

    has_same_grade_or_raw = any(
        (_numeric_grade(a.grade) == num_grade)
        or a.anchor_type in {"RAW_CONSENSUS", "EXACT_GCC_SOLD", "TEMPORALLY_ADJUSTED_ESTIMATE"}
        for a in sold_anchors
    )

    # 5. Classify Category
    # Is it a crossgrade, secondary-grader discount, or illiquid price discovery?
    has_psa_crossgrade_anchor = any(
        (a.grader or "").upper() == "PSA" and (_numeric_grade(a.grade) == num_grade or _numeric_grade(a.grade) == 10.0)
        for a in sold_anchors
    )
    if crossgrade_probability is not None and crossgrade_probability > 0.5 and has_psa_crossgrade_anchor and (num_grade or 0) >= 9.0:
        category = CATEGORY_CROSSGRADE_OPPORTUNITY
        main_thesis = f"High-grade {norm_grader} {norm_grade} with potential PSA crossgrade ({upside_ratio:.1f}x) [DIAGNOSTIC]"

    elif norm_grader in {"PCA", "BGS", "CGC"} and (num_grade or 0) >= 9.5 and psa_anchors and exact_grader_liquidity in {LIQUIDITY_MODERATE, LIQUIDITY_HIGH}:
        category = CATEGORY_SECONDARY_GRADER_DISCOUNT
        main_thesis = f"Secondary grader {norm_grader} {norm_grade} priced at substantial discount vs PSA benchmark ({upside_ratio:.1f}x)"
    elif norm_grader not in {"PSA"} and exact_grader_liquidity in {LIQUIDITY_MODERATE, LIQUIDITY_HIGH}:
        category = CATEGORY_SECONDARY_GRADER_DISCOUNT
        main_thesis = f"Liquid {norm_grader} {norm_grade} market trading at discount vs market consensus ({upside_ratio:.1f}x)"
    elif temporal_adjustment is not None and temporal_adjustment.applied:
        category = CATEGORY_ILLIQUID_PRICE_DISCOVERY
        main_thesis = f"Old exact {norm_grader} {norm_grade} sale ({temporal_adjustment.historical_exact_grader_sale:.2f}€) temporally rebased via PSA appreciation to {temporal_adjustment.temporally_adjusted_central:.2f}€ ({upside_ratio:.1f}x upside)"
    else:
        category = CATEGORY_ILLIQUID_PRICE_DISCOVERY
        main_thesis = f"Sparse exact {norm_grader} {norm_grade} liquidity rescued by {len(sold_anchors)} adjacent sold/consensus anchors ({upside_ratio:.1f}x upside)"

    # 6. Manual Review Recommendation Decision
    if not has_same_grade_or_raw:
        # Wide-grade / higher-grade anchors alone cannot create an opportunity without same-grade/exact/raw proof
        manual_review = False
    elif not has_same_lang_or_raw and len(sold_anchors) <= 1:
        manual_review = False
    elif category == CATEGORY_CROSSGRADE_OPPORTUNITY:
        # Crossgrade opportunities remain diagnostic without a dedicated live crossgrade pipeline
        manual_review = False
    elif gcc_price >= credible_high_ref * 0.85 or upside_ratio < 1.25:
        manual_review = False
    elif evidence_quality == EVIDENCE_QUALITY_LOW and uncertainty in {UNCERTAINTY_VERY_HIGH}:
        manual_review = False
    elif upside_ratio >= 1.50 and len(sold_anchors) >= 1 and evidence_quality in {EVIDENCE_QUALITY_MODERATE, EVIDENCE_QUALITY_STRONG}:
        manual_review = True
    elif upside_ratio >= 1.30 and len(sold_anchors) >= 2 and has_same_lang_or_raw:
        manual_review = True
    elif temporal_adjustment is not None and temporal_adjustment.applied and (temporal_adjustment.implicit_discount_pct or 0) >= 25.0:
        manual_review = True
    else:
        manual_review = False


    t_res = temporal_adjustment
    return PriceDiscoverySignal(
        listing_identity=listing_identity,
        gcc_price=gcc_price,
        grader=norm_grader,
        grade=norm_grade,
        exact_grader_liquidity=exact_grader_liquidity,
        category=category,
        liquidity=exact_grader_liquidity,
        evidence_quality=evidence_quality,
        uncertainty=uncertainty,
        grader_spread=grader_spread,
        credible_high_reference=credible_high_ref,
        asymmetric_upside_ratio=upside_ratio,
        main_thesis=main_thesis,
        credible_adjacent_anchors=tuple(credible_anchors),
        crossgrade_required=False,
        manual_review_recommended=manual_review,
        diagnostics=(f"CATEGORY_{category}", f"QUALITY_{evidence_quality}", f"UNCERTAINTY_{uncertainty}"),
        historical_exact_grader_sale=t_res.historical_exact_grader_sale if t_res else None,
        historical_reference_price=t_res.historical_reference_price if t_res else None,
        historical_grader_reference_ratio=t_res.historical_grader_reference_ratio if t_res else None,
        current_robust_reference_value=t_res.current_robust_reference_value if t_res else None,
        temporally_adjusted_low=t_res.temporally_adjusted_low if t_res else None,
        temporally_adjusted_central=t_res.temporally_adjusted_central if t_res else None,
        temporally_adjusted_high=t_res.temporally_adjusted_high if t_res else None,
        implicit_discount_pct=t_res.implicit_discount_pct if t_res else None,
        is_extrapolated=t_res.is_extrapolated if t_res else False,
        extrapolation_type=t_res.extrapolation_type if t_res else None,
        evidence_level=t_res.evidence_level if t_res else (EVIDENCE_LEVEL_EXACT_RECENT if recent_sales_count >= 1 else EVIDENCE_LEVEL_CROSS_GRADER_ONLY if len(sold_anchors) >= 1 else EVIDENCE_LEVEL_MANUAL_REVIEW_NO_ESTIMATE),
    )
