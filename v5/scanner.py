from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, List, Optional, Sequence, Tuple

from .grading import (
    ConservativeProbabilityPolicy,
    GradeAssessmentProvider,
    GradeProviderError,
)
from .models import (
    PSA10_DEPENDENT,
    CostInputs,
    EbayListing,
    GradeAssessment,
    GradeImagePair,
    GradeProbabilities,
    ImageQuality,
    MarketValue,
    MarketValues,
    ScanDecision,
    ScanDiagnostic,
    StructuredGradingStatus,
)
from .valuation import (
    IncompleteValuation,
    MarketDataProvider,
    MarketDataUnavailable,
    calculate_expected_value,
    grade_profit_scenarios,
)


IDENTITY_AMBIGUOUS = "IDENTITY_AMBIGUOUS"
NOT_STRUCTURED_RAW = "NOT_STRUCTURED_RAW"
RAW_PRICE_BELOW_MINIMUM = "RAW_PRICE_BELOW_MINIMUM"
RAW_PRICE_ABOVE_MAXIMUM = "RAW_PRICE_ABOVE_MAXIMUM"
INSUFFICIENT_PHOTOS = "INSUFFICIENT_PHOTOS"
BACK_IMAGE_MISSING = "BACK_IMAGE_MISSING"
LOW_IMAGE_QUALITY = "LOW_IMAGE_QUALITY"
UNKNOWN_IMAGE_QUALITY = "UNKNOWN_IMAGE_QUALITY"
GRADING_UNAVAILABLE = "GRADING_UNAVAILABLE"
MARKET_DATA_UNAVAILABLE = "MARKET_DATA_UNAVAILABLE"
INSUFFICIENT_PSA_DATA = "INSUFFICIENT_PSA_DATA"
SIGNIFICANT_COSTS_UNKNOWN = "SIGNIFICANT_COSTS_UNKNOWN"
CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
INSUFFICIENT_MAX_PLAUSIBLE_UPSIDE = "INSUFFICIENT_MAX_PLAUSIBLE_UPSIDE"
VISUAL_GRADING_QUOTA_REACHED = "VISUAL_GRADING_QUOTA_REACHED"
NON_PROFITABLE_EV = "NON_PROFITABLE_EV"
ROI_BELOW_THRESHOLD = "ROI_BELOW_THRESHOLD"
CHEAP_FILTER_PASSED = "CHEAP_FILTER_PASSED"


@dataclass(frozen=True)
class SafeguardConfig:
    # Ces bornes appartiennent uniquement aux cartes RAW de V5.
    raw_min_price_eur: Decimal = Decimal("0")
    raw_max_price_eur: Optional[Decimal] = None
    minimum_max_plausible_profit_eur: Decimal = Decimal("0")
    minimum_max_plausible_roi_percent: Decimal = Decimal("0")
    maximum_paid_gradings_per_run: int = 0
    minimum_psa_samples: int = 2
    minimum_roi_percent: Decimal = Decimal("0")
    maximum_psa10_ev_share: Decimal = Decimal("0.65")
    minimum_grade_confidence: Optional[float] = None

    def __post_init__(self) -> None:
        if self.raw_min_price_eur < 0:
            raise ValueError("RAW_MIN_PRICE_EUR ne peut pas etre negatif")
        if (
            self.raw_max_price_eur is not None
            and self.raw_max_price_eur < self.raw_min_price_eur
        ):
            raise ValueError("RAW_MAX_PRICE_EUR doit etre >= RAW_MIN_PRICE_EUR")
        if self.maximum_paid_gradings_per_run < 0:
            raise ValueError("RAW_MAX_PAID_GRADINGS_PER_RUN ne peut pas etre negatif")
        if self.minimum_psa_samples < 1:
            raise ValueError("V5_MIN_PSA_SAMPLES doit etre >= 1")

    @classmethod
    def from_env(cls) -> "SafeguardConfig":
        raw_confidence = os.getenv("V5_MIN_GRADE_CONFIDENCE", "").strip()
        raw_max = os.getenv("RAW_MAX_PRICE_EUR", "").strip()
        return cls(
            # Ne jamais consulter MIN_PRICE_EUR ou MAX_PRICE_EUR de V4 ici.
            raw_min_price_eur=Decimal(os.getenv("RAW_MIN_PRICE_EUR", "0")),
            raw_max_price_eur=Decimal(raw_max) if raw_max else None,
            minimum_max_plausible_profit_eur=Decimal(
                os.getenv("RAW_MIN_PLAUSIBLE_PROFIT_EUR", "0")
            ),
            minimum_max_plausible_roi_percent=Decimal(
                os.getenv("RAW_MIN_PLAUSIBLE_ROI_PERCENT", "0")
            ),
            maximum_paid_gradings_per_run=int(
                os.getenv("RAW_MAX_PAID_GRADINGS_PER_RUN", "0")
            ),
            minimum_psa_samples=int(os.getenv("V5_MIN_PSA_SAMPLES", "2")),
            minimum_roi_percent=Decimal(os.getenv("V5_MIN_ROI_PERCENT", "0")),
            maximum_psa10_ev_share=Decimal(
                os.getenv("V5_MAX_PSA10_EV_SHARE", "0.65")
            ),
            minimum_grade_confidence=(
                float(raw_confidence) if raw_confidence else None
            ),
        )


@dataclass(frozen=True)
class ScanRequest:
    listing: EbayListing
    image_pair: GradeImagePair
    costs: CostInputs


@dataclass(frozen=True)
class CheapFilterResult:
    request: ScanRequest
    eligible_for_visual_grading: bool
    reasons: Tuple[str, ...]
    market_values: Optional[MarketValues] = None
    total_cost_if_graded: Optional[Decimal] = None
    psa10_profit: Optional[Decimal] = None
    psa9_profit: Optional[Decimal] = None
    psa8_profit: Optional[Decimal] = None
    maximum_plausible_roi: Optional[Decimal] = None

    @property
    def priority(self) -> Tuple[Decimal, Decimal, Decimal]:
        """Favorise PSA9 avant PSA10 pour limiter les paris PSA10-only."""

        return (
            self.psa9_profit
            if self.psa9_profit is not None
            else Decimal("-Infinity"),
            self.psa10_profit
            if self.psa10_profit is not None
            else Decimal("-Infinity"),
            self.maximum_plausible_roi
            if self.maximum_plausible_roi is not None
            else Decimal("-Infinity"),
        )


class RawCardScanner:
    def __init__(
        self,
        grade_provider: GradeAssessmentProvider,
        market_provider: MarketDataProvider,
        probability_policy: Optional[ConservativeProbabilityPolicy] = None,
        safeguards: Optional[SafeguardConfig] = None,
    ) -> None:
        self.grade_provider = grade_provider
        self.market_provider = market_provider
        self.probability_policy = (
            probability_policy or ConservativeProbabilityPolicy.from_env()
        )
        self.safeguards = safeguards or SafeguardConfig.from_env()

    def cheap_filter(self, request: ScanRequest) -> CheapFilterResult:
        """Filtre sans aucun appel au provider de grading visuel."""

        listing = request.listing
        identity = listing.identity
        if listing.grading_status is not StructuredGradingStatus.RAW:
            return CheapFilterResult(request, False, (NOT_STRUCTURED_RAW,))
        if listing.price < self.safeguards.raw_min_price_eur:
            return CheapFilterResult(request, False, (RAW_PRICE_BELOW_MINIMUM,))
        if (
            self.safeguards.raw_max_price_eur is not None
            and listing.price > self.safeguards.raw_max_price_eur
        ):
            return CheapFilterResult(request, False, (RAW_PRICE_ABOVE_MAXIMUM,))
        if not identity.is_unambiguous_pokemon():
            detail = identity.ambiguities or identity.missing_required_fields()
            return CheapFilterResult(
                request, False, (IDENTITY_AMBIGUOUS,) + tuple(detail)
            )
        if request.costs.unknown_fields():
            return CheapFilterResult(
                request,
                False,
                (SIGNIFICANT_COSTS_UNKNOWN,) + request.costs.unknown_fields(),
            )

        try:
            market_values = self.market_provider.values_for(identity)
        except MarketDataUnavailable as exc:
            return CheapFilterResult(
                request, False, (MARKET_DATA_UNAVAILABLE, str(exc))
            )
        insufficient_psa = _insufficient_psa_evidence(
            market_values, self.safeguards.minimum_psa_samples
        )
        if insufficient_psa:
            return CheapFilterResult(
                request,
                False,
                (INSUFFICIENT_PSA_DATA,) + insufficient_psa,
                market_values=market_values,
            )

        try:
            psa10_profit, psa9_profit, psa8_profit = grade_profit_scenarios(
                market_values, request.costs
            )
            total_cost = request.costs.fixed_total()
        except IncompleteValuation as exc:
            reason = (
                CURRENCY_MISMATCH
                if "devise" in str(exc).casefold()
                else MARKET_DATA_UNAVAILABLE
            )
            return CheapFilterResult(
                request,
                False,
                (reason, str(exc)),
                market_values=market_values,
            )
        maximum_roi = psa10_profit / total_cost * Decimal("100")
        if (
            psa10_profit < self.safeguards.minimum_max_plausible_profit_eur
            or maximum_roi < self.safeguards.minimum_max_plausible_roi_percent
        ):
            return CheapFilterResult(
                request,
                False,
                (INSUFFICIENT_MAX_PLAUSIBLE_UPSIDE,),
                market_values=market_values,
                total_cost_if_graded=total_cost,
                psa10_profit=psa10_profit,
                psa9_profit=psa9_profit,
                psa8_profit=psa8_profit,
                maximum_plausible_roi=maximum_roi,
            )

        # Les controles photo restent gratuits et precedent le grading visuel.
        photo_reasons = _photo_rejection_reasons(request)
        if photo_reasons:
            return CheapFilterResult(
                request,
                False,
                photo_reasons,
                market_values=market_values,
                total_cost_if_graded=total_cost,
                psa10_profit=psa10_profit,
                psa9_profit=psa9_profit,
                psa8_profit=psa8_profit,
                maximum_plausible_roi=maximum_roi,
            )
        return CheapFilterResult(
            request,
            True,
            (CHEAP_FILTER_PASSED,),
            market_values=market_values,
            total_cost_if_graded=total_cost,
            psa10_profit=psa10_profit,
            psa9_profit=psa9_profit,
            psa8_profit=psa8_profit,
            maximum_plausible_roi=maximum_roi,
        )

    def shortlist(self, requests: Iterable[ScanRequest]) -> List[CheapFilterResult]:
        return sorted(
            (
                result
                for result in (self.cheap_filter(request) for request in requests)
                if result.eligible_for_visual_grading
            ),
            key=lambda result: result.priority,
            reverse=True,
        )

    def evaluate(self, request: ScanRequest) -> ScanDiagnostic:
        cheap_result = self.cheap_filter(request)
        if not cheap_result.eligible_for_visual_grading:
            return _diagnostic_from_cheap(cheap_result)
        if self.safeguards.maximum_paid_gradings_per_run < 1:
            return _diagnostic_from_cheap(
                cheap_result, reasons=(VISUAL_GRADING_QUOTA_REACHED,)
            )
        return self._expensive_visual_grading(cheap_result)

    def _expensive_visual_grading(
        self, cheap_result: CheapFilterResult
    ) -> ScanDiagnostic:
        request = cheap_result.request
        listing = request.listing
        identity = listing.identity
        market_values = cheap_result.market_values
        if market_values is None:
            return _diagnostic_from_cheap(
                cheap_result, reasons=(MARKET_DATA_UNAVAILABLE,)
            )
        try:
            assessment = self.grade_provider.assess(request.image_pair, identity)
        except GradeProviderError as exc:
            return _diagnostic_from_cheap(
                cheap_result, reasons=(GRADING_UNAVAILABLE, str(exc))
            )
        if assessment.image_quality is ImageQuality.LOW:
            return _diagnostic_from_cheap(
                cheap_result,
                reasons=(LOW_IMAGE_QUALITY,),
                assessment=assessment,
            )
        if assessment.image_quality is ImageQuality.UNKNOWN:
            return _diagnostic_from_cheap(
                cheap_result,
                reasons=(UNKNOWN_IMAGE_QUALITY,),
                assessment=assessment,
            )
        if (
            self.safeguards.minimum_grade_confidence is not None
            and assessment.confidence is not None
            and assessment.confidence < self.safeguards.minimum_grade_confidence
        ):
            return _diagnostic_from_cheap(
                cheap_result,
                reasons=("GRADE_CONFIDENCE_TOO_LOW",),
                assessment=assessment,
            )

        probabilities = self.probability_policy.probabilities_for(assessment)
        try:
            valuation = calculate_expected_value(
                probabilities, market_values, request.costs, assessment
            )
        except IncompleteValuation as exc:
            reason = (
                CURRENCY_MISMATCH
                if "devise" in str(exc).casefold()
                else MARKET_DATA_UNAVAILABLE
            )
            return _diagnostic_from_cheap(
                cheap_result,
                reasons=(reason, str(exc)),
                assessment=assessment,
                probabilities=probabilities,
            )

        risk_flags = []
        psa10_contribution = (
            Decimal(str(probabilities.psa10)) * market_values.psa10.amount
            if market_values.psa10 is not None
            else Decimal("0")
        )
        psa10_share = (
            psa10_contribution / valuation.ev_gross
            if valuation.ev_gross > 0
            else Decimal("1")
        )
        if (
            valuation.psa9_profit < 0
            or psa10_share > self.safeguards.maximum_psa10_ev_share
        ):
            risk_flags.append(PSA10_DEPENDENT)

        reasons = []
        if valuation.expected_profit <= 0:
            reasons.append(NON_PROFITABLE_EV)
        if valuation.expected_roi < self.safeguards.minimum_roi_percent:
            reasons.append(ROI_BELOW_THRESHOLD)
        if PSA10_DEPENDENT in risk_flags:
            reasons.append(PSA10_DEPENDENT)
        decision = ScanDecision.REJECTED if reasons else ScanDecision.RETAINED
        if not reasons:
            reasons.append("EV_POSITIVE_WITH_SAFEGUARDS_PASSED")

        return ScanDiagnostic(
            listing=listing,
            identity=identity,
            decision=decision,
            reasons=tuple(reasons),
            risk_flags=tuple(risk_flags),
            assessment=assessment,
            probabilities=probabilities,
            market_values=market_values,
            valuation=valuation,
            costs=request.costs,
            total_cost_if_graded=valuation.total_cost_if_graded,
            psa10_profit=valuation.psa10_profit,
            psa9_profit=valuation.psa9_profit,
            psa8_profit=valuation.psa8_profit,
            confidence=_diagnostic_confidence(assessment.confidence, market_values),
        )

    def scan_and_rank(self, requests: Iterable[ScanRequest]) -> List[ScanDiagnostic]:
        cheap_results = [self.cheap_filter(request) for request in requests]
        rejected = [
            _diagnostic_from_cheap(result)
            for result in cheap_results
            if not result.eligible_for_visual_grading
        ]
        eligible = sorted(
            (
                result
                for result in cheap_results
                if result.eligible_for_visual_grading
            ),
            key=lambda result: result.priority,
            reverse=True,
        )
        quota = self.safeguards.maximum_paid_gradings_per_run
        selected = eligible[:quota]
        deferred = eligible[quota:]
        diagnostics = rejected + [
            self._expensive_visual_grading(result) for result in selected
        ]
        diagnostics.extend(
            _diagnostic_from_cheap(
                result, reasons=(VISUAL_GRADING_QUOTA_REACHED,)
            )
            for result in deferred
        )
        return sorted(
            diagnostics,
            key=lambda diagnostic: (
                diagnostic.retained,
                diagnostic.valuation.expected_roi
                if diagnostic.valuation is not None
                else Decimal("-Infinity"),
                diagnostic.psa9_profit
                if diagnostic.psa9_profit is not None
                else Decimal("-Infinity"),
            ),
            reverse=True,
        )


def _diagnostic_from_cheap(
    result: CheapFilterResult,
    reasons: Optional[Sequence[str]] = None,
    assessment: Optional[GradeAssessment] = None,
    probabilities: Optional[GradeProbabilities] = None,
) -> ScanDiagnostic:
    request = result.request
    return ScanDiagnostic(
        listing=request.listing,
        identity=request.listing.identity,
        decision=ScanDecision.REJECTED,
        reasons=tuple(reasons or result.reasons),
        assessment=assessment,
        probabilities=probabilities,
        market_values=result.market_values,
        costs=request.costs,
        total_cost_if_graded=result.total_cost_if_graded,
        psa10_profit=result.psa10_profit,
        psa9_profit=result.psa9_profit,
        psa8_profit=result.psa8_profit,
        confidence=(
            _diagnostic_confidence(None, result.market_values)
            if result.market_values is not None
            else "insuffisante"
        ),
    )


def _photo_rejection_reasons(request: ScanRequest) -> Tuple[str, ...]:
    listing = request.listing
    if len(listing.image_urls) < 2:
        return (INSUFFICIENT_PHOTOS,)
    if not request.image_pair.back_url:
        return (BACK_IMAGE_MISSING,)
    if not request.image_pair.is_complete():
        return (INSUFFICIENT_PHOTOS,)
    if (
        request.image_pair.front_url not in listing.image_urls
        or request.image_pair.back_url not in listing.image_urls
    ):
        return (INSUFFICIENT_PHOTOS, "IMAGE_PAIR_NOT_IN_EBAY_LISTING")
    return ()


def _insufficient_psa_evidence(
    values: MarketValues, minimum_samples: int
) -> Tuple[str, ...]:
    insufficient = list(values.missing_ev_grades())
    for grade, value in (("PSA9", values.psa9), ("PSA10", values.psa10)):
        if value is None:
            continue
        if value.sample_size is None:
            insufficient.append(f"{grade}_SAMPLE_SIZE_UNKNOWN")
        elif value.sample_size < minimum_samples:
            insufficient.append(f"{grade}_INSUFFICIENT_SAMPLES")
    return tuple(dict.fromkeys(insufficient))


def _diagnostic_confidence(
    grade_confidence: Optional[float], values: MarketValues
) -> str:
    market_confidences = [
        (value.confidence or "").casefold()
        for value in values.ev_values()
        if value is not None
    ]
    if grade_confidence is not None and grade_confidence >= 0.8 and all(
        confidence in {"high", "elevee", "élevée"}
        for confidence in market_confidences
    ):
        return "elevee"
    if grade_confidence is None or any(
        confidence in {"low", "faible", ""} for confidence in market_confidences
    ):
        return "faible"
    return "moyenne"


def costs_from_listing(
    listing: EbayListing,
    buyer_fees: Optional[Decimal],
    grading_fee: Optional[Decimal],
    shipping_for_grading: Optional[Decimal],
    marketplace_selling_fee_rate: Optional[Decimal],
    other_costs: Optional[Decimal],
) -> CostInputs:
    return CostInputs(
        purchase_price=listing.price,
        shipping_to_buyer=listing.shipping_price,
        buyer_fees=buyer_fees,
        grading_fee=grading_fee,
        shipping_for_grading=shipping_for_grading,
        marketplace_selling_fee_rate=marketplace_selling_fee_rate,
        other_costs=other_costs,
        currency=listing.currency,
    )


def costs_from_env(listing: EbayListing) -> CostInputs:
    """Construit les couts V5 sans remplacer une valeur absente par zero."""

    def configured_decimal(name: str) -> Optional[Decimal]:
        raw = os.getenv(name, "").strip()
        return Decimal(raw) if raw else None

    return costs_from_listing(
        listing=listing,
        buyer_fees=configured_decimal("V5_BUYER_FEES"),
        grading_fee=configured_decimal("V5_GRADING_FEE"),
        shipping_for_grading=configured_decimal("V5_GRADING_SHIPPING"),
        marketplace_selling_fee_rate=configured_decimal("V5_SELLING_FEE_RATE"),
        other_costs=configured_decimal("V5_OTHER_COSTS"),
    )


def _money(value: Optional[Decimal], currency: str) -> str:
    if value is None:
        return "N/D"
    return f"{value.quantize(Decimal('0.01'))} {currency}"


def _probability(value: Optional[float]) -> str:
    if value is None:
        return "N/D"
    return f"{value * 100:.1f}%"


def _market(value: Optional[MarketValue]) -> str:
    if value is None:
        return "N/D"
    return _money(value.amount, value.currency)


def format_diagnostic(diagnostic: ScanDiagnostic) -> str:
    listing = diagnostic.listing
    costs = diagnostic.costs
    assessment = diagnostic.assessment
    probabilities = diagnostic.probabilities
    values = diagnostic.market_values
    valuation = diagnostic.valuation
    try:
        pre_grading = (
            _money(costs.pre_grading_total(), costs.currency) if costs else "N/D"
        )
    except ValueError:
        pre_grading = "N/D"
    break_even = (
        _probability(valuation.break_even_probability_psa10)
        if valuation is not None
        else "N/D"
    )
    risk = ", ".join(diagnostic.risk_flags) or "aucun flag"
    classification = (
        "speculatif / PSA10_DEPENDENT"
        if PSA10_DEPENDENT in diagnostic.risk_flags
        else "non speculatif"
    )

    lines = [
        "RAW CANDIDATE",
        f"Carte: {diagnostic.identity.display_name()}",
        f"Source: {listing.source}",
        f"URL: {listing.url}",
        f"Prix: {_money(listing.price, listing.currency)}",
        f"Cout total pre-grading: {pre_grading}",
        f"Cout total si grading: {_money(diagnostic.total_cost_if_graded, listing.currency)}",
        "",
        "Pre-grade:",
        f"Predicted: {assessment.predicted_grade if assessment else 'N/D'}",
        f"P10: {_probability(probabilities.psa10 if probabilities else None)}",
        f"P9: {_probability(probabilities.psa9 if probabilities else None)}",
        f"P8: {_probability(probabilities.psa8 if probabilities else None)}",
        f"P<=7: {_probability(probabilities.psa7_or_lower if probabilities else None)}",
        "",
        "Valeurs:",
        f"Raw: {_market(values.raw if values else None)}",
        f"PSA8: {_market(values.psa8 if values else None)}",
        f"PSA9: {_market(values.psa9 if values else None)}",
        f"PSA10: {_market(values.psa10 if values else None)}",
        "",
        f"Resultat PSA10: {_money(diagnostic.psa10_profit, listing.currency)}",
        f"Resultat PSA9: {_money(diagnostic.psa9_profit, listing.currency)}",
        f"Resultat PSA8: {_money(diagnostic.psa8_profit, listing.currency)}",
        "Stress PSA9:",
        f"profit/perte: {_money(diagnostic.psa9_profit, listing.currency)}",
        f"EV probabiliste brute: {_money(valuation.ev_gross if valuation else None, listing.currency)}",
        f"EV probabiliste nette: {_money(valuation.ev_net if valuation else None, listing.currency)}",
        f"Profit EV: {_money(valuation.expected_profit if valuation else None, listing.currency)}",
        (
            f"ROI EV: {valuation.expected_roi.quantize(Decimal('0.01'))}%"
            if valuation
            else "ROI EV: N/D"
        ),
        f"Break-even P(PSA10): {break_even}",
        "",
        f"Risque: {risk}",
        f"Classification: {classification}",
        f"Confiance: {diagnostic.confidence}",
        (
            "Pourquoi retenue: " + "; ".join(diagnostic.reasons)
            if diagnostic.retained
            else "Pourquoi rejetee: " + "; ".join(diagnostic.reasons)
        ),
    ]
    return "\n".join(lines)
