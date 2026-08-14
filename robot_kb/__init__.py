"""Isolated P0 card knowledge-base foundation.

This package is intentionally not imported by the production V4 watcher.  It
contains SQLite/PostgreSQL domain contracts for isolated shadow collection.
"""

from .domain import (
    ClaimRole,
    Directness,
    EvidenceMethod,
    InclusionState,
    ObservationRelationshipType,
    ObservationType,
    OpportunityState,
    PriceKnowledge,
    ResolutionState,
    SourceKind,
    VariantValuationScenario,
    classify_opportunity,
)
from .repository import (
    CandidateInput,
    FXNormalization,
    IdempotencyConflict,
    KnowledgeBase,
    KnowledgeBaseError,
    PriceComponent,
    ProvenanceError,
    ResolvedField,
    VariantError,
)

__all__ = [
    "CandidateInput",
    "ClaimRole",
    "Directness",
    "EvidenceMethod",
    "FXNormalization",
    "IdempotencyConflict",
    "InclusionState",
    "KnowledgeBase",
    "KnowledgeBaseError",
    "ObservationRelationshipType",
    "ObservationType",
    "OpportunityState",
    "PriceComponent",
    "PriceKnowledge",
    "ProvenanceError",
    "ResolutionState",
    "ResolvedField",
    "SourceKind",
    "VariantError",
    "VariantValuationScenario",
    "classify_opportunity",
]
