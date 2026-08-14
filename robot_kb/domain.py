"""Pure domain contracts for identity evidence and scenario valuation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence


class StringEnum(str, Enum):
    """A Python 3.9-compatible string enum."""

    def __str__(self) -> str:
        return self.value


class ObservationType(StringEnum):
    SALE_TRANSACTION = "SALE_TRANSACTION"
    LISTING_SNAPSHOT = "LISTING_SNAPSHOT"
    PROVIDER_METRIC_OBSERVATION = "PROVIDER_METRIC_OBSERVATION"
    POPULATION_OBSERVATION = "POPULATION_OBSERVATION"
    FX_RATE_OBSERVATION = "FX_RATE_OBSERVATION"


class SourceKind(StringEnum):
    PROVIDER = "PROVIDER"
    CATALOG = "CATALOG"
    LISTING = "LISTING"
    HUMAN = "HUMAN"


class EvidenceMethod(StringEnum):
    STRUCTURED_FIELD = "STRUCTURED_FIELD"
    TITLE_PARSE = "TITLE_PARSE"
    OCR = "OCR"
    VISUAL_REFERENCE = "VISUAL_REFERENCE"
    MANUAL = "MANUAL"
    DERIVED_RULE = "DERIVED_RULE"


class Directness(StringEnum):
    DIRECT_ASSERTION = "DIRECT_ASSERTION"
    DETERMINISTIC_DERIVATION = "DETERMINISTIC_DERIVATION"
    STATISTICAL_INFERENCE = "STATISTICAL_INFERENCE"


class ResolutionState(StringEnum):
    PROVEN = "PROVEN"
    SUPPORTED = "SUPPORTED"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


class ClaimRole(StringEnum):
    EVIDENCE = "EVIDENCE"
    REQUEST_TARGET = "REQUEST_TARGET"


class ObservationRelationshipType(StringEnum):
    DUPLICATE_OF = "DUPLICATE_OF"
    AGGREGATOR_OF = "AGGREGATOR_OF"
    RELIST_OF = "RELIST_OF"
    REVISION_OF = "REVISION_OF"
    CANCELS = "CANCELS"
    VOIDS = "VOIDS"


class PriceKnowledge(StringEnum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class InclusionState(StringEnum):
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class OpportunityState(StringEnum):
    EXACT_VARIANT_OPPORTUNITY = "EXACT_VARIANT_OPPORTUNITY"
    ROBUST_VARIANT_OPPORTUNITY = "ROBUST_VARIANT_OPPORTUNITY"
    MICROVARIANT_DEPENDENT_OPPORTUNITY = "MICROVARIANT_DEPENDENT_OPPORTUNITY"
    SCENARIO_DATA_INCOMPLETE_REVIEW = "SCENARIO_DATA_INCOMPLETE_REVIEW"
    NO_OPPORTUNITY = "NO_OPPORTUNITY"
    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
    IDENTITY_UNBOUNDED = "IDENTITY_UNBOUNDED"
    MARKET_UNCONFIRMED = "MARKET_UNCONFIRMED"


@dataclass(frozen=True)
class VariantValuationScenario:
    """One independently valued exact commercial-print scenario.

    ``passes_threshold`` deliberately remains a supplied decision outcome in
    P0.  This package defines the state contract; it does not forecast value or
    choose a production discount threshold.
    """

    variant_profile_id: str
    market_confirmed: bool
    passes_threshold: Optional[bool]
    market_value_minor: Optional[int] = None
    target_price_minor: Optional[int] = None
    currency: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.variant_profile_id:
            raise ValueError("variant_profile_id is required")
        if not self.market_confirmed and self.passes_threshold is not None:
            raise ValueError(
                "an unconfirmed market cannot have a threshold decision"
            )
        if self.market_confirmed and self.passes_threshold is None:
            raise ValueError(
                "a confirmed scenario must state whether it passes"
            )
        if (self.market_value_minor is None) != (self.currency is None):
            raise ValueError("market value and currency must be supplied together")


def classify_opportunity(
    scenarios: Sequence[VariantValuationScenario],
    *,
    identity_conflict: bool = False,
    identity_bounded: bool = True,
    exact_variant_profile_id: Optional[str] = None,
) -> OpportunityState:
    """Classify a finite set of independently valued variant scenarios.

    The function never blends scenarios.  Missing data has precedence over a
    negative decision, so a partially valued candidate set cannot become
    ``NO_OPPORTUNITY``.
    """

    if identity_conflict:
        return OpportunityState.IDENTITY_CONFLICT
    if not identity_bounded:
        return OpportunityState.IDENTITY_UNBOUNDED

    if exact_variant_profile_id is not None:
        if len(scenarios) != 1:
            raise ValueError(
                "exact_variant_profile_id requires exactly one candidate scenario"
            )
        if scenarios[0].variant_profile_id != exact_variant_profile_id:
            raise ValueError(
                "exact_variant_profile_id must identify the sole candidate scenario"
            )
    elif len(scenarios) == 1:
        raise ValueError(
            "a single candidate scenario requires proven exact variant identity"
        )

    if not scenarios:
        return OpportunityState.MARKET_UNCONFIRMED

    profile_ids = [scenario.variant_profile_id for scenario in scenarios]
    if len(set(profile_ids)) != len(profile_ids):
        raise ValueError("each plausible variant may appear only once")

    unconfirmed = [scenario for scenario in scenarios if not scenario.market_confirmed]
    if len(unconfirmed) == len(scenarios):
        return OpportunityState.MARKET_UNCONFIRMED
    if unconfirmed:
        return OpportunityState.SCENARIO_DATA_INCOMPLETE_REVIEW

    passing = [scenario for scenario in scenarios if scenario.passes_threshold]
    if len(passing) == len(scenarios):
        if len(scenarios) == 1:
            return OpportunityState.EXACT_VARIANT_OPPORTUNITY
        if len(scenarios) < 2:
            raise ValueError("robust opportunity requires multiple plausible variants")
        return OpportunityState.ROBUST_VARIANT_OPPORTUNITY
    if passing:
        return OpportunityState.MICROVARIANT_DEPENDENT_OPPORTUNITY
    return OpportunityState.NO_OPPORTUNITY
