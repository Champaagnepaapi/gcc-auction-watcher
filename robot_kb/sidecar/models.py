"""Typed contracts shared by the read-only shadow observation sidecar."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

from robot_kb.domain import (
    ClaimRole,
    Directness,
    EvidenceMethod,
    ObservationType,
    ResolutionState,
    SourceKind,
)
from robot_kb.repository import PriceComponent


@dataclass(frozen=True)
class RawSourceRecord:
    """One immutable payload returned by a source collector."""

    source_code: str
    source_name: str
    source_role: str
    source_native_record_id: str
    payload: Mapping[str, Any]
    retrieved_at: str
    source_updated_at: Optional[str] = None
    object_type: str = "SOURCE_RECORD"
    external_native_id: Optional[str] = None


@dataclass(frozen=True)
class IdentityClaim:
    """One source-backed claim; missing provider fields create no claim."""

    field_name: str
    value: Any
    source_kind: SourceKind
    evidence_method: EvidenceMethod = EvidenceMethod.STRUCTURED_FIELD
    directness: Directness = Directness.DIRECT_ASSERTION
    resolution_state: ResolutionState = ResolutionState.SUPPORTED
    claim_role: ClaimRole = ClaimRole.EVIDENCE


@dataclass(frozen=True)
class NormalizedObservation:
    """A typed fact ready for the P0 append-only knowledge repository."""

    observation_type: ObservationType
    source_native_record_id: str
    observed_at: str
    fact: Mapping[str, Any]
    identity_subject_type: str
    identity_subject_label: str
    identity_namespace: str
    identity_identifier_value: str
    unresolved_dimensions: Tuple[str, ...]
    claims: Tuple[IdentityClaim, ...] = ()
    source_updated_at: Optional[str] = None
    upstream_market_code: Optional[str] = None
    upstream_market_name: Optional[str] = None
    event_at: Optional[str] = None
    event_time_precision: str = "UNKNOWN"
    prices: Tuple[PriceComponent, ...] = ()
    exact_identity_eligible: bool = True
    genuine_sale_evidence: bool = False


@dataclass(frozen=True)
class NormalizationBatch:
    """Normalized facts plus evidence-rejection diagnostics for one payload."""

    observations: Tuple[NormalizedObservation, ...]
    sale_candidates_rejected: int = 0
    ambiguous_sale_records: int = 0
    metric_alias_conflicts: int = 0
    monetary_facts_rejected: int = 0
    rejected_record: bool = False


@dataclass(frozen=True)
class CollectionResult:
    """Records fetched from one independently isolated source request."""

    records: Tuple[RawSourceRecord, ...]
    rejected_malformed_records: int = 0
    crawl_truncated: bool = False


@dataclass
class ShadowDiagnostics:
    """Operational summary with no production decision semantics."""

    source_records_fetched: int = 0
    observations_accepted: int = 0
    observations_replayed: int = 0
    unresolved_identities_retained: int = 0
    exact_identities_linked: int = 0
    provider_metrics_stored: int = 0
    sale_transactions_stored: int = 0
    sale_candidates_rejected: int = 0
    ambiguous_sale_records: int = 0
    duplicate_sale_replays: int = 0
    metric_alias_conflicts: int = 0
    monetary_facts_rejected: int = 0
    crawl_batches_truncated: int = 0
    rejected_malformed_records: int = 0
    source_failures: int = 0
    failure_messages: list[str] = field(default_factory=list)

    def record_failure(self, source_name: str, error: BaseException) -> None:
        self.source_failures += 1
        self.failure_messages.append(
            f"{source_name}: {type(error).__name__}: {error}"
        )

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "source_records_fetched": self.source_records_fetched,
            "observations_accepted": self.observations_accepted,
            "observations_replayed": self.observations_replayed,
            "unresolved_identities_retained": self.unresolved_identities_retained,
            "exact_identities_linked": self.exact_identities_linked,
            "provider_metrics_stored": self.provider_metrics_stored,
            "sale_transactions_stored": self.sale_transactions_stored,
            "sale_candidates_rejected": self.sale_candidates_rejected,
            "ambiguous_sale_records": self.ambiguous_sale_records,
            "duplicate_sale_replays": self.duplicate_sale_replays,
            "metric_alias_conflicts": self.metric_alias_conflicts,
            "monetary_facts_rejected": self.monetary_facts_rejected,
            "crawl_batches_truncated": self.crawl_batches_truncated,
            "rejected_malformed_records": self.rejected_malformed_records,
            "source_failures": self.source_failures,
            "failure_messages": list(self.failure_messages),
        }


NormalizerResult = NormalizationBatch
