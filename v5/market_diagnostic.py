"""Diagnostic V5 de valorisation strictement hors ligne et agrege."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Tuple

from .image_detection import BACK_IMAGE_CONFIRMED, BACK_IMAGE_UNKNOWN
from .market_values.aggregator import MarketValueAggregator
from .market_values.economic import (
    COST_MODEL_INCOMPLETE,
    ECONOMIC_REJECT_EVEN_PSA10,
    GRADE9_PROFITABLE,
    PSA10_DEPENDENT,
    RAW_ARBITRAGE,
    CostModel,
    evaluate_economic_pre_filter,
)
from .market_values.models import (
    MARKET_VALUE_CONFLICT,
    MARKET_VALUES_MISSING,
    AggregationStatus,
    MarketValues,
)
from .models import CardIdentity


@dataclass(frozen=True)
class OfflineCase:
    identity: CardIdentity
    values: Optional[MarketValues]
    costs: CostModel
    back_state: str


def _identity(number: str) -> CardIdentity:
    return CardIdentity(
        game="Pokemon TCG",
        card_name=f"Offline Card {number}",
        set="Offline Test Set",
        card_number=number,
        year=2024,
        language="English",
    )


def _values(
    identity: CardIdentity,
    ungraded: str,
    grade8: str,
    grade9: str,
    psa10: str,
) -> MarketValues:
    return MarketValues(
        source="offline PriceCharting-shaped fixture",
        currency="USD",
        ungraded_value=Decimal(ungraded),
        grade8_generic_value=Decimal(grade8),
        grade9_generic_value=Decimal(grade9),
        psa10_value=Decimal(psa10),
        matched_identity=identity,
        match_confidence=Decimal("1"),
        matched_product_id=f"offline-{identity.card_number}",
        fetched_at=datetime.now(timezone.utc),
        limitations=("offline fixture",),
    )


def _costs(purchase: str, grading_fee: str, grading_shipping: str) -> CostModel:
    return CostModel(
        raw_purchase_price=Decimal(purchase),
        buyer_fees=Decimal("0"),
        domestic_shipping=Decimal("0"),
        international_shipping=Decimal("0"),
        grading_fee=Decimal(grading_fee),
        grading_shipping=Decimal(grading_shipping),
        vault_fee=Decimal("0"),
        selling_fee_pct=Decimal("0"),
        selling_fixed_fee=Decimal("0"),
        fx_buffer_pct=Decimal("0"),
        other_costs=Decimal("0"),
        currency="USD",
    )


def offline_cases() -> Tuple[OfflineCase, ...]:
    a, b, c, d, e, f = (_identity(str(index)) for index in range(1, 7))
    return (
        OfflineCase(a, _values(a, "3", "6", "8", "60"), _costs("2", "20", "5"), BACK_IMAGE_CONFIRMED),
        OfflineCase(b, _values(b, "15", "40", "55", "100"), _costs("10", "20", "5"), BACK_IMAGE_CONFIRMED),
        OfflineCase(c, _values(c, "25", "30", "35", "40"), _costs("30", "10", "5"), BACK_IMAGE_CONFIRMED),
        OfflineCase(d, None, _costs("2", "20", "5"), BACK_IMAGE_CONFIRMED),
        # Cas ambigu PriceCharting : aucune valorisation n'est transmise.
        OfflineCase(e, None, _costs("2", "20", "5"), BACK_IMAGE_CONFIRMED),
        OfflineCase(f, _values(f, "15", "40", "55", "100"), _costs("10", "20", "5"), BACK_IMAGE_UNKNOWN),
    )


def render_summary() -> str:
    counts = {
        "found": 0,
        "missing": 0,
        "conflicts": 0,
        "raw": 0,
        "grade9": 0,
        "psa10": 0,
        "reject": 0,
        "costs": 0,
        "back": 0,
    }
    aggregator = MarketValueAggregator()
    cases = offline_cases()
    for case in cases:
        aggregate = aggregator.aggregate(
            case.identity, (case.values,) if case.values is not None else ()
        )
        if aggregate.status is AggregationStatus.AVAILABLE:
            counts["found"] += 1
        elif MARKET_VALUE_CONFLICT in aggregate.reasons:
            counts["conflicts"] += 1
        else:
            counts["missing"] += 1
        result = evaluate_economic_pre_filter(aggregate, case.costs, case.back_state)
        counts["raw"] += RAW_ARBITRAGE in result.signals
        counts["grade9"] += GRADE9_PROFITABLE in result.signals
        counts["psa10"] += PSA10_DEPENDENT in result.signals
        counts["reject"] += ECONOMIC_REJECT_EVEN_PSA10 in result.signals
        counts["costs"] += COST_MODEL_INCOMPLETE in result.signals
        counts["back"] += result.back_missing_but_economic_analysis_continued

    return "\n".join(
        (
            "=== V5 MARKET VALUATION SUMMARY ===",
            f"identities evaluated: {len(cases)}",
            f"market values found: {counts['found']}",
            f"market values missing: {counts['missing']}",
            f"market value conflicts: {counts['conflicts']}",
            f"raw arbitrage: {counts['raw']}",
            f"grade9 profitable: {counts['grade9']}",
            f"psa10 dependent: {counts['psa10']}",
            f"economic reject even psa10: {counts['reject']}",
            f"cost model incomplete: {counts['costs']}",
            f"back missing but economic analysis continued: {counts['back']}",
            "PriceCharting:",
            "enabled: false",
            "live calls: 0",
            f"offline matches tested: {len(cases)}",
            "Marketplace Insights:",
            "enabled: false",
            "live calls: 0",
            "PSA Sales:",
            "status: UNAVAILABLE",
            "CardGrader calls: 0",
            "Purchases: 0",
            "Bids: 0",
            "Checkout: 0",
            "Persisted eBay records: 0",
        )
    )


def main() -> int:
    print(render_summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
