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


def _numeric_grade(raw_grade: object) -> Optional[float]:
    if raw_grade is None:
        return None
    try:
        return float(str(raw_grade).strip())
    except (ValueError, TypeError):
        return None


def evaluate_price_discovery(
    *,
    listing_identity: str,
    gcc_price: float,
    grader: str,
    grade: str,
    language: str = "fr",
    exact_grader_sales: Sequence[Any] = (),
    adjacent_anchors: Sequence[AdjacentAnchor] = (),
    raw_consensus: Optional[Any] = None,
    crossgrade_probability: Optional[float] = None,
) -> PriceDiscoverySignal:
    """
    Evaluate grader spread and price discovery for a listing using credible adjacent evidence.
    """
    norm_grader = (grader or "").strip().upper()
    norm_grade = (grade or "").strip()
    num_grade = _numeric_grade(norm_grade)
    norm_lang = (language or "fr").strip().lower()

    exact_sales_count = len(exact_grader_sales)
    if exact_sales_count == 0:
        exact_grader_liquidity = LIQUIDITY_LOW
    elif exact_sales_count < 4:
        exact_grader_liquidity = LIQUIDITY_MODERATE
    else:
        exact_grader_liquidity = LIQUIDITY_HIGH

    # 1. Process and filter adjacent anchors
    credible_anchors: list[AdjacentAnchor] = []
    has_active_ask_only = True
    
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

    # If PSA same-grade or top-grade (PSA 10) sold anchor exists, use it as benchmark reference
    psa_anchors = [
        a for a in sold_anchors
        if (a.grader or "").upper() == "PSA" and (_numeric_grade(a.grade) == num_grade or ((num_grade or 0) >= 9.5 and _numeric_grade(a.grade) == 10.0))
    ]
    if psa_anchors:
        credible_high_ref = round(max(a.price for a in psa_anchors), 2)


    upside_ratio = round(credible_high_ref / max(0.01, gcc_price), 2) if gcc_price > 0 else 1.0

    # 3. Calculate Grader Spread
    if psa_anchors:
        psa_ref = max(a.price for a in psa_anchors)
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

    # 5. Classify Category
    # Is it a crossgrade, secondary-grader discount, or illiquid price discovery?
    if crossgrade_probability is not None and crossgrade_probability > 0.5 and psa_anchors and (num_grade or 0) >= 9.0:
        category = CATEGORY_CROSSGRADE_OPPORTUNITY
        main_thesis = f"High-grade {norm_grader} {norm_grade} with strong PSA crossgrade upside ({upside_ratio:.1f}x)"
    elif norm_grader in {"PCA", "BGS", "CGC"} and (num_grade or 0) >= 9.5 and psa_anchors and exact_grader_liquidity in {LIQUIDITY_MODERATE, LIQUIDITY_HIGH}:
        category = CATEGORY_SECONDARY_GRADER_DISCOUNT
        main_thesis = f"Secondary grader {norm_grader} {norm_grade} priced at substantial discount vs PSA benchmark ({upside_ratio:.1f}x)"
    elif norm_grader not in {"PSA"} and exact_grader_liquidity in {LIQUIDITY_MODERATE, LIQUIDITY_HIGH}:
        category = CATEGORY_SECONDARY_GRADER_DISCOUNT
        main_thesis = f"Liquid {norm_grader} {norm_grade} market trading at discount vs market consensus ({upside_ratio:.1f}x)"
    else:
        category = CATEGORY_ILLIQUID_PRICE_DISCOVERY
        main_thesis = f"Sparse exact {norm_grader} {norm_grade} liquidity rescued by {len(sold_anchors)} adjacent sold/consensus anchors ({upside_ratio:.1f}x upside)"


    # 6. Manual Review Recommendation Decision
    # Negative regression check: Liquid secondary market where ask >= fair market => no discount signal
    if gcc_price >= credible_high_ref * 0.85 or upside_ratio < 1.25:
        manual_review = False
    elif evidence_quality == EVIDENCE_QUALITY_LOW and uncertainty in {UNCERTAINTY_VERY_HIGH}:
        manual_review = False
    elif upside_ratio >= 1.50 and len(sold_anchors) >= 1 and evidence_quality in {EVIDENCE_QUALITY_MODERATE, EVIDENCE_QUALITY_STRONG}:
        manual_review = True
    elif upside_ratio >= 1.30 and len(sold_anchors) >= 2:
        manual_review = True
    else:
        manual_review = False

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
    )
