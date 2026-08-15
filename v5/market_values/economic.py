from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Optional, Tuple

from ..image_detection import BACK_IMAGE_CONFIRMED
from .models import (
    MARKET_VALUE_CONFLICT,
    MARKET_VALUES_MISSING,
    AggregatedMarketValues,
    AggregationStatus,
    MarketLevel,
)


COST_MODEL_INCOMPLETE = "COST_MODEL_INCOMPLETE"
ECONOMIC_REJECT_EVEN_PSA10 = "ECONOMIC_REJECT_EVEN_PSA10"
PSA10_DEPENDENT = "PSA10_DEPENDENT"
GRADE9_PROFITABLE = "GRADE9_PROFITABLE"
RAW_ARBITRAGE = "RAW_ARBITRAGE"
GRADING_VISUAL_CONFIDENCE_REDUCED = "GRADING_VISUAL_CONFIDENCE_REDUCED"
RAW_MARKET_INSUFFICIENT = "RAW_MARKET_INSUFFICIENT"
RAW_PATH_REJECTED = "RAW_PATH_REJECTED"
RAW_RESALE = "RAW_RESALE"
NO_RECOMMENDED_PATH = "NONE"
MINIMUM_RAW_MATCH_CONFIDENCE = Decimal("0.95")


@dataclass(frozen=True)
class CostModel:
    raw_purchase_price: Optional[Decimal]
    buyer_fees: Optional[Decimal]
    domestic_shipping: Optional[Decimal]
    international_shipping: Optional[Decimal]
    grading_fee: Optional[Decimal]
    grading_shipping: Optional[Decimal]
    vault_fee: Optional[Decimal]
    selling_fee_pct: Optional[Decimal]
    selling_fixed_fee: Optional[Decimal]
    fx_buffer_pct: Optional[Decimal]
    other_costs: Optional[Decimal]
    currency: str

    def __post_init__(self) -> None:
        values = (
            self.raw_purchase_price,
            self.buyer_fees,
            self.domestic_shipping,
            self.international_shipping,
            self.grading_fee,
            self.grading_shipping,
            self.vault_fee,
            self.selling_fee_pct,
            self.selling_fixed_fee,
            self.fx_buffer_pct,
            self.other_costs,
        )
        if any(value is not None and value < 0 for value in values):
            raise ValueError("Les couts et pourcentages V5 ne peuvent pas etre negatifs")
        if not self.currency.strip():
            raise ValueError("La devise du modele de couts est obligatoire")

    @classmethod
    def from_env(
        cls,
        currency: str,
        raw_purchase_price: Optional[Decimal] = None,
    ) -> "CostModel":
        def configured(name: str) -> Optional[Decimal]:
            raw = os.getenv(name, "").strip()
            return Decimal(raw) if raw else None

        return cls(
            raw_purchase_price=(
                raw_purchase_price
                if raw_purchase_price is not None
                else configured("RAW_PURCHASE_PRICE")
            ),
            buyer_fees=configured("BUYER_FEES"),
            domestic_shipping=configured("DOMESTIC_SHIPPING"),
            international_shipping=configured("INTERNATIONAL_SHIPPING"),
            grading_fee=configured("GRADING_FEE"),
            grading_shipping=configured("GRADING_SHIPPING"),
            vault_fee=configured("VAULT_FEE"),
            selling_fee_pct=configured("SELLING_FEE_PCT"),
            selling_fixed_fee=configured("SELLING_FIXED_FEE"),
            fx_buffer_pct=configured("FX_BUFFER_PCT"),
            other_costs=configured("OTHER_COSTS"),
            currency=currency,
        )

    def unknown_fields(self) -> Tuple[str, ...]:
        pairs = (
            ("RAW_PURCHASE_PRICE", self.raw_purchase_price),
            ("BUYER_FEES", self.buyer_fees),
            ("DOMESTIC_SHIPPING", self.domestic_shipping),
            ("INTERNATIONAL_SHIPPING", self.international_shipping),
            ("GRADING_FEE", self.grading_fee),
            ("GRADING_SHIPPING", self.grading_shipping),
            ("VAULT_FEE", self.vault_fee),
            ("SELLING_FEE_PCT", self.selling_fee_pct),
            ("SELLING_FIXED_FEE", self.selling_fixed_fee),
            ("FX_BUFFER_PCT", self.fx_buffer_pct),
            ("OTHER_COSTS", self.other_costs),
        )
        return tuple(name for name, value in pairs if value is None)

    def raw_unknown_fields(self) -> Tuple[str, ...]:
        pairs = (
            ("RAW_PURCHASE_PRICE", self.raw_purchase_price),
            ("BUYER_FEES", self.buyer_fees),
            ("DOMESTIC_SHIPPING", self.domestic_shipping),
            ("INTERNATIONAL_SHIPPING", self.international_shipping),
            ("SELLING_FEE_PCT", self.selling_fee_pct),
            ("SELLING_FIXED_FEE", self.selling_fixed_fee),
            ("FX_BUFFER_PCT", self.fx_buffer_pct),
            ("OTHER_COSTS", self.other_costs),
        )
        return tuple(name for name, value in pairs if value is None)

    def raw_fixed_costs(self) -> Decimal:
        if self.raw_unknown_fields():
            raise ValueError(COST_MODEL_INCOMPLETE)
        values = (
            self.raw_purchase_price,
            self.buyer_fees,
            self.domestic_shipping,
            self.international_shipping,
            self.other_costs,
        )
        return sum((value for value in values if value is not None), Decimal("0"))

    def all_in_cost_if_graded(self) -> Decimal:
        missing = self.unknown_fields()
        if missing:
            raise ValueError(COST_MODEL_INCOMPLETE)
        fixed_values = (
            self.raw_purchase_price,
            self.buyer_fees,
            self.domestic_shipping,
            self.international_shipping,
            self.grading_fee,
            self.grading_shipping,
            self.vault_fee,
            self.other_costs,
        )
        return sum((value for value in fixed_values if value is not None), Decimal("0"))

    def net_sale(self, market_value: Decimal) -> Decimal:
        if self.unknown_fields():
            raise ValueError(COST_MODEL_INCOMPLETE)
        percentage = (self.selling_fee_pct or Decimal("0")) + (
            self.fx_buffer_pct or Decimal("0")
        )
        variable_fees = market_value * percentage / Decimal("100")
        return market_value - variable_fees - (self.selling_fixed_fee or Decimal("0"))

    def raw_net_sale(self, market_value: Decimal) -> Decimal:
        if self.raw_unknown_fields():
            raise ValueError(COST_MODEL_INCOMPLETE)
        percentage = (self.selling_fee_pct or Decimal("0")) + (
            self.fx_buffer_pct or Decimal("0")
        )
        variable_fees = market_value * percentage / Decimal("100")
        return market_value - variable_fees - (self.selling_fixed_fee or Decimal("0"))

    def raw_total_cost_basis(self, market_value: Decimal) -> Decimal:
        return market_value - self.raw_net_sale(market_value) + self.raw_fixed_costs()


@dataclass(frozen=True)
class EconomicThresholds:
    minimum_profit: Decimal = Decimal("0")
    minimum_roi_percent: Decimal = Decimal("0")

    @classmethod
    def from_env(cls) -> "EconomicThresholds":
        return cls(
            minimum_profit=Decimal(
                os.getenv("RAW_MIN_PLAUSIBLE_PROFIT_EUR", "0")
            ),
            minimum_roi_percent=Decimal(
                os.getenv("RAW_MIN_PLAUSIBLE_ROI_PERCENT", "0")
            ),
        )


@dataclass(frozen=True)
class EconomicScenario:
    level: MarketLevel
    market_value: Decimal
    net_sale: Decimal
    profit: Decimal
    roi_percent: Optional[Decimal]
    total_cost_basis: Decimal


@dataclass(frozen=True)
class EconomicPreFilterResult:
    can_continue: bool
    signals: Tuple[str, ...]
    risk_flags: Tuple[str, ...]
    all_in_cost: Optional[Decimal]
    scenarios: Mapping[MarketLevel, EconomicScenario]
    psa10_upside_multiple: Optional[Decimal]
    grade9_upside_multiple: Optional[Decimal]
    back_missing_but_economic_analysis_continued: bool
    raw_market_sufficient: bool = False
    raw_path_evaluated: bool = False
    raw_profitable: bool = False
    raw_rejected: bool = False
    graded_comparison_available: bool = False
    raw_beats_grading: bool = False
    grading_beats_raw: bool = False
    graded_absent_but_raw_evaluable: bool = False
    recommended_path: str = NO_RECOMMENDED_PATH


def evaluate_economic_pre_filter(
    market: AggregatedMarketValues,
    costs: CostModel,
    back_image_state: str,
    thresholds: EconomicThresholds = EconomicThresholds(),
) -> EconomicPreFilterResult:
    reduced_visual_confidence = back_image_state != BACK_IMAGE_CONFIRMED
    risk_flags = (
        (GRADING_VISUAL_CONFIDENCE_REDUCED,) if reduced_visual_confidence else ()
    )
    if market.status is AggregationStatus.CONFLICT:
        return EconomicPreFilterResult(
            False, (MARKET_VALUE_CONFLICT,), risk_flags, None, {}, None, None, False
        )
    if market.status is AggregationStatus.MISSING:
        return EconomicPreFilterResult(
            False, (MARKET_VALUES_MISSING,), risk_flags, None, {}, None, None, False
        )
    if costs.currency != market.currency:
        return EconomicPreFilterResult(
            False,
            (MARKET_VALUE_CONFLICT, "CURRENCY_MISMATCH"),
            risk_flags,
            None,
            {},
            None,
            None,
            False,
        )

    scenarios = {}
    raw_level = market.level(MarketLevel.UNGRADED)
    raw_provider_evidence = tuple(
        value
        for value in market.provider_values
        if value.ungraded_value is not None
    )
    raw_market_sufficient = bool(
        raw_level.central_value is not None
        and raw_level.central_value > 0
        and raw_level.low_value is not None
        and raw_level.source_count >= 1
        and raw_level.confidence in {"medium", "high"}
        and not raw_level.disagreement
        and raw_provider_evidence
        and all(
            value.match_confidence is not None
            and value.match_confidence >= MINIMUM_RAW_MATCH_CONFIDENCE
            for value in raw_provider_evidence
        )
    )
    raw_path_evaluated = False
    raw_cost_missing = costs.raw_unknown_fields()
    if raw_market_sufficient and not raw_cost_missing:
        prudent_raw = raw_level.low_value
        if prudent_raw is not None and prudent_raw > 0:
            raw_basis = costs.raw_total_cost_basis(prudent_raw)
            raw_profit = prudent_raw - raw_basis
            raw_roi = (
                raw_profit / raw_basis * Decimal("100") if raw_basis > 0 else None
            )
            scenarios[MarketLevel.UNGRADED] = EconomicScenario(
                MarketLevel.UNGRADED,
                prudent_raw,
                costs.raw_net_sale(prudent_raw),
                raw_profit,
                raw_roi,
                raw_basis,
            )
            raw_path_evaluated = raw_basis > 0

    grading_missing = costs.unknown_fields()
    graded_market_available = any(
        market.level(level).central_value is not None
        for level in (
            MarketLevel.GRADE8_GENERIC,
            MarketLevel.GRADE9_GENERIC,
            MarketLevel.PSA10,
        )
    )
    all_in = None
    if not grading_missing:
        all_in = costs.all_in_cost_if_graded()
        for level in (
            MarketLevel.GRADE8_GENERIC,
            MarketLevel.GRADE9_GENERIC,
            MarketLevel.PSA10,
        ):
            market_value = market.level(level).central_value
            if market_value is None:
                continue
            net_sale = costs.net_sale(market_value)
            profit = net_sale - all_in
            roi = profit / all_in * Decimal("100") if all_in > 0 else None
            scenarios[level] = EconomicScenario(
                level, market_value, net_sale, profit, roi, all_in
            )

    if not scenarios:
        material_missing = ()
        if raw_market_sufficient and raw_cost_missing:
            material_missing += raw_cost_missing
        if graded_market_available and grading_missing:
            material_missing += grading_missing
        if material_missing:
            missing = tuple(dict.fromkeys(material_missing))
            return EconomicPreFilterResult(
                False,
                (COST_MODEL_INCOMPLETE,) + missing,
                risk_flags,
                all_in,
                {},
                None,
                None,
                False,
                raw_market_sufficient=raw_market_sufficient,
            )
        if not raw_market_sufficient and not graded_market_available:
            return EconomicPreFilterResult(
                False,
                (RAW_MARKET_INSUFFICIENT,),
                risk_flags,
                all_in,
                {},
                None,
                None,
                False,
            )
        return EconomicPreFilterResult(
            False,
            (MARKET_VALUES_MISSING,),
            risk_flags,
            all_in,
            {},
            None,
            None,
            False,
        )

    def profitable(level: MarketLevel) -> bool:
        if level not in scenarios:
            return False
        scenario = scenarios[level]
        roi_ok = (
            scenario.roi_percent is not None
            and scenario.roi_percent >= thresholds.minimum_roi_percent
        )
        return scenario.profit >= thresholds.minimum_profit and roi_ok

    signals = []
    raw_profitable = profitable(MarketLevel.UNGRADED)
    raw_rejected = raw_path_evaluated and not raw_profitable
    grade9_available = MarketLevel.GRADE9_GENERIC in scenarios
    grade9_profitable = profitable(MarketLevel.GRADE9_GENERIC)
    psa10_available = MarketLevel.PSA10 in scenarios
    psa10_profitable = profitable(MarketLevel.PSA10)
    if raw_profitable:
        signals.append(RAW_ARBITRAGE)
    elif raw_path_evaluated:
        signals.append(RAW_PATH_REJECTED)
    elif not raw_market_sufficient:
        signals.append(RAW_MARKET_INSUFFICIENT)
    if grade9_profitable:
        signals.append(GRADE9_PROFITABLE)
    if psa10_available and psa10_profitable and grade9_available and not grade9_profitable:
        signals.append(PSA10_DEPENDENT)
    if psa10_available and not psa10_profitable and not (raw_profitable or grade9_profitable):
        signals.append(ECONOMIC_REJECT_EVEN_PSA10)
    if not signals:
        signals.append(MARKET_VALUES_MISSING)

    graded_absent = not any(
        market.level(level).central_value is not None
        for level in (
            MarketLevel.GRADE8_GENERIC,
            MarketLevel.GRADE9_GENERIC,
            MarketLevel.PSA10,
        )
    )

    return EconomicPreFilterResult(
        can_continue=raw_profitable or grade9_profitable or psa10_profitable,
        signals=tuple(signals),
        risk_flags=risk_flags,
        all_in_cost=all_in,
        scenarios=scenarios,
        psa10_upside_multiple=(
            scenarios[MarketLevel.PSA10].market_value / all_in
            if all_in is not None and all_in > 0 and MarketLevel.PSA10 in scenarios
            else None
        ),
        grade9_upside_multiple=(
            scenarios[MarketLevel.GRADE9_GENERIC].market_value / all_in
            if all_in is not None
            and all_in > 0
            and MarketLevel.GRADE9_GENERIC in scenarios
            else None
        ),
        back_missing_but_economic_analysis_continued=reduced_visual_confidence,
        raw_market_sufficient=raw_market_sufficient,
        raw_path_evaluated=raw_path_evaluated,
        raw_profitable=raw_profitable,
        raw_rejected=raw_rejected,
        # Un scenario de grade ne constitue pas une EV de grading. La
        # comparaison reste indisponible sans assessment visuel autorise.
        graded_comparison_available=False,
        graded_absent_but_raw_evaluable=raw_path_evaluated and graded_absent,
        recommended_path=RAW_RESALE if raw_profitable else NO_RECOMMENDED_PATH,
    )
