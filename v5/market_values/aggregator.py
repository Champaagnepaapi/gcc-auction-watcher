from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from typing import Iterable, Tuple

from ..models import CardIdentity
from .models import (
    MARKET_VALUE_CONFLICT,
    MARKET_VALUES_MISSING,
    AggregatedLevel,
    AggregatedMarketValues,
    AggregationStatus,
    MarketLevel,
    MarketValues,
    identity_key,
)


@dataclass(frozen=True)
class AggregatorConfig:
    maximum_relative_dispersion: Decimal = Decimal("0.50")


class MarketValueAggregator:
    def __init__(self, config: AggregatorConfig = AggregatorConfig()) -> None:
        self.config = config

    def aggregate(
        self, identity: CardIdentity, provider_values: Iterable[MarketValues]
    ) -> AggregatedMarketValues:
        values = tuple(value for value in provider_values if value.has_any_value())
        empty = {
            level: AggregatedLevel(None, None, None, 0, (), "none", False, None)
            for level in MarketLevel
        }
        if not values:
            return AggregatedMarketValues(
                identity, None, empty, AggregationStatus.MISSING, (MARKET_VALUES_MISSING,)
            )

        expected_key = identity_key(identity)
        mismatches = tuple(
            value
            for value in values
            if value.matched_identity is None
            or identity_key(value.matched_identity) != expected_key
        )
        currencies = {value.currency for value in values}
        if mismatches or len(currencies) != 1:
            reasons = [MARKET_VALUE_CONFLICT]
            if mismatches:
                reasons.append("IDENTITY_MISMATCH")
            if len(currencies) != 1:
                reasons.append("CURRENCY_MISMATCH")
            return AggregatedMarketValues(
                identity,
                next(iter(currencies)) if len(currencies) == 1 else None,
                empty,
                AggregationStatus.CONFLICT,
                tuple(reasons),
                values,
            )

        levels = {}
        any_disagreement = False
        for level in MarketLevel:
            observations = tuple(
                (value.value_for(level), value.source)
                for value in values
                if value.value_for(level) is not None
            )
            if not observations:
                levels[level] = empty[level]
                continue
            amounts = tuple(item[0] for item in observations)
            central = Decimal(str(median(amounts)))
            low = min(amounts)
            high = max(amounts)
            dispersion = (high - low) / central if central > 0 else None
            disagreement = bool(
                dispersion is not None
                and dispersion > self.config.maximum_relative_dispersion
            )
            any_disagreement = any_disagreement or disagreement
            source_names = tuple(dict.fromkeys(item[1] for item in observations))
            confidence = "low" if disagreement else ("high" if len(source_names) > 1 else "medium")
            levels[level] = AggregatedLevel(
                central,
                low,
                high,
                len(source_names),
                source_names,
                confidence,
                disagreement,
                dispersion,
            )

        status = AggregationStatus.CONFLICT if any_disagreement else AggregationStatus.AVAILABLE
        reasons: Tuple[str, ...] = (MARKET_VALUE_CONFLICT,) if any_disagreement else ()
        return AggregatedMarketValues(
            identity,
            next(iter(currencies)),
            levels,
            status,
            reasons,
            values,
        )
