from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Optional, Protocol, Tuple

from .models import (
    CardIdentity,
    CostInputs,
    GradeAssessment,
    GradeProbabilities,
    MarketValue,
    MarketValues,
    ValuationResult,
    decimal_from,
)


HUNDRED = Decimal("100")
ONE = Decimal("1")


class MarketDataUnavailable(RuntimeError):
    pass


class IncompleteValuation(ValueError):
    pass


class MarketDataProvider(Protocol):
    def values_for(self, identity: CardIdentity) -> MarketValues:
        ...


class StaticMarketDataProvider:
    """Provider hors ligne utile pour fixtures et branchements futurs.

    Aucune valeur absente n'est completee ou extrapolee.
    """

    def __init__(self, values: Mapping[Tuple[str, str, str], MarketValues]) -> None:
        self.values = dict(values)

    def values_for(self, identity: CardIdentity) -> MarketValues:
        key = (
            identity.card_name or "",
            identity.set or "",
            identity.card_number or "",
        )
        if key not in self.values:
            raise MarketDataUnavailable("Aucune donnee de marche pour cette identite")
        return self.values[key]


def _market_amount(value: Optional[MarketValue], grade: str) -> Decimal:
    if value is None:
        raise IncompleteValuation(f"Valeur {grade} absente")
    return value.amount


def _profit_at_value(value: Decimal, costs: CostInputs) -> Decimal:
    if costs.marketplace_selling_fee_rate is None:
        raise IncompleteValuation("Taux de frais de vente inconnu")
    return value * (ONE - costs.marketplace_selling_fee_rate) - costs.fixed_total()


def grade_profit_scenarios(
    market_values: MarketValues, costs: CostInputs
) -> Tuple[Decimal, Decimal, Decimal]:
    """Profits nets si le resultat reel est respectivement PSA10, PSA9 ou PSA8."""

    missing = tuple(
        grade
        for grade, value in (
            ("PSA10", market_values.psa10),
            ("PSA9", market_values.psa9),
            ("PSA8", market_values.psa8),
        )
        if value is None
    )
    if missing:
        raise IncompleteValuation("Valeurs de grade absentes: " + ", ".join(missing))
    if costs.unknown_fields():
        raise IncompleteValuation(
            "Couts significatifs inconnus: " + ", ".join(costs.unknown_fields())
        )
    selling_rate = costs.marketplace_selling_fee_rate
    if selling_rate is None or not Decimal("0") <= selling_rate < ONE:
        raise IncompleteValuation("Taux de frais marketplace invalide")
    if costs.fixed_total() <= 0:
        raise IncompleteValuation("Le cout total investi doit etre strictement positif")
    currencies = market_values.currencies()
    if len(currencies) != 1 or currencies[0] != costs.currency:
        raise IncompleteValuation(
            "Conversion de devise interdite sans provider de change explicite"
        )
    return (
        _profit_at_value(_market_amount(market_values.psa10, "PSA10"), costs),
        _profit_at_value(_market_amount(market_values.psa9, "PSA9"), costs),
        _profit_at_value(_market_amount(market_values.psa8, "PSA8"), costs),
    )


def calculate_expected_value(
    probabilities: GradeProbabilities,
    market_values: MarketValues,
    costs: CostInputs,
    assessment: GradeAssessment,
) -> ValuationResult:
    missing = market_values.missing_ev_grades()
    if missing:
        raise IncompleteValuation("Valeurs de grade absentes: " + ", ".join(missing))
    if costs.unknown_fields():
        raise IncompleteValuation(
            "Couts significatifs inconnus: " + ", ".join(costs.unknown_fields())
        )
    currencies = market_values.currencies()
    if len(currencies) != 1 or currencies[0] != costs.currency:
        raise IncompleteValuation(
            "Conversion de devise interdite sans provider de change explicite"
        )
    selling_rate = costs.marketplace_selling_fee_rate
    if selling_rate is None or not Decimal("0") <= selling_rate < ONE:
        raise IncompleteValuation("Taux de frais marketplace invalide")

    psa10 = _market_amount(market_values.psa10, "PSA10")
    psa9 = _market_amount(market_values.psa9, "PSA9")
    psa8 = _market_amount(market_values.psa8, "PSA8")
    lower = _market_amount(market_values.psa7_or_lower, "PSA7_OR_LOWER")
    psa10_profit, psa9_profit, psa8_profit = grade_profit_scenarios(
        market_values, costs
    )

    ev_gross = (
        decimal_from(probabilities.psa10) * psa10
        + decimal_from(probabilities.psa9) * psa9
        + decimal_from(probabilities.psa8) * psa8
        + decimal_from(probabilities.psa7_or_lower) * lower
    )

    # EV nette: produit de revente apres frais de vente, grading et autres
    # couts operationnels, mais avant prix d'acquisition et livraison d'achat.
    operational_costs = sum(
        (
            costs.buyer_fees or Decimal("0"),
            costs.grading_fee or Decimal("0"),
            costs.shipping_for_grading or Decimal("0"),
            costs.other_costs or Decimal("0"),
        ),
        Decimal("0"),
    )
    ev_net = ev_gross * (ONE - selling_rate) - operational_costs
    acquisition_costs = (costs.purchase_price or Decimal("0")) + (
        costs.shipping_to_buyer or Decimal("0")
    )
    expected_profit = ev_net - acquisition_costs
    fixed_total = costs.fixed_total()
    if fixed_total <= 0:
        raise IncompleteValuation("Le cout total investi doit etre strictement positif")
    expected_roi = expected_profit / fixed_total * HUNDRED

    stress_psa9_profit = _profit_at_value(psa9, costs)
    if assessment.predicted_grade >= 9.75:
        stress_grade = "PSA9"
        stress_value = psa9
    elif assessment.predicted_grade >= 8.75:
        stress_grade = "PSA8"
        stress_value = psa8
    else:
        stress_grade = "PSA7_OR_LOWER"
        stress_value = lower
    stress_profit = _profit_at_value(stress_value, costs)

    non10_probability = 1.0 - probabilities.psa10
    break_even_probability: Optional[float]
    if non10_probability <= 0:
        break_even_probability = float(
            fixed_total / ((ONE - selling_rate) * psa10)
        )
    else:
        non10_expected = (
            decimal_from(probabilities.psa9) * psa9
            + decimal_from(probabilities.psa8) * psa8
            + decimal_from(probabilities.psa7_or_lower) * lower
        ) / decimal_from(non10_probability)
        required_sale_value = fixed_total / (ONE - selling_rate)
        denominator = psa10 - non10_expected
        if denominator <= 0:
            break_even_probability = None
        else:
            threshold = float((required_sale_value - non10_expected) / denominator)
            break_even_probability = max(0.0, min(1.0, threshold))

    return ValuationResult(
        ev_gross=ev_gross,
        ev_net=ev_net,
        expected_profit=expected_profit,
        expected_roi=expected_roi,
        break_even_probability_psa10=break_even_probability,
        total_cost_if_graded=fixed_total,
        psa10_profit=psa10_profit,
        psa9_profit=psa9_profit,
        psa8_profit=psa8_profit,
        worst_case_grade="PSA7_OR_LOWER",
        worst_case_profit=_profit_at_value(lower, costs),
        stress_grade=stress_grade,
        stress_profit=stress_profit,
        stress_psa9_profit=stress_psa9_profit,
    )
