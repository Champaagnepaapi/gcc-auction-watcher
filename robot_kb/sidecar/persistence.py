"""Persistence adapter from normalized sidecar facts to the P0 repository."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping, Optional, Sequence

from robot_kb.domain import ObservationType, ResolutionState
from robot_kb.repository import (
    IdempotencyConflict,
    KnowledgeBase,
    KnowledgeBaseError,
)

from .collectors import utc_now
from .models import (
    IdentityClaim,
    NormalizedObservation,
    RawSourceRecord,
    ShadowDiagnostics,
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _observation_key(
    source_system_id: str,
    source_record_id: str,
    observation: NormalizedObservation,
) -> str:
    identity = {
        "sidecar_version": 1,
        "source_system_id": source_system_id,
        "source_record_id": source_record_id,
        "source_native_record_id": observation.source_native_record_id,
        "observation_type": observation.observation_type.value,
        "observed_at": observation.observed_at,
        "source_updated_at": observation.source_updated_at,
        "upstream_market_code": observation.upstream_market_code,
        "metric_name": observation.fact.get("metric_name"),
    }
    digest = hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()
    return f"obskey_{digest}"


class ShadowKnowledgePersistence:
    """Small adapter that adds no mutable state outside the P0 ledger."""

    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        *,
        clock: Callable[[], str] = utc_now,
    ) -> None:
        self.knowledge_base = knowledge_base
        self.clock = clock

    def _identity_subject(
        self,
        source_record_id: str,
        external_object_id: str,
        observation: NormalizedObservation,
    ) -> str:
        existing = self.knowledge_base.connection.execute(
            """
            SELECT id FROM identity_subject
            WHERE source_record_id = ?
              AND external_object_id = ?
              AND subject_type = ?
              AND subject_label = ?
            ORDER BY created_at, id LIMIT 1
            """,
            (
                source_record_id,
                external_object_id,
                observation.identity_subject_type,
                observation.identity_subject_label,
            ),
        ).fetchone()
        if existing is not None:
            return existing["id"]
        return self.knowledge_base.create_identity_subject(
            observation.identity_subject_type,
            source_record_id=source_record_id,
            external_object_id=external_object_id,
            subject_label=observation.identity_subject_label,
        )

    def _append_claim_once(
        self,
        source_record_id: str,
        identity_subject_id: str,
        claim: IdentityClaim,
    ) -> str:
        claimed_json = _canonical_json(claim.value)
        existing = self.knowledge_base.connection.execute(
            """
            SELECT id FROM field_claim
            WHERE source_record_id = ?
              AND identity_subject_id = ?
              AND field_name = ?
              AND claimed_value_json = ?
              AND source_kind = ?
              AND evidence_method = ?
              AND directness = ?
              AND resolution_state = ?
              AND claim_role = ?
            ORDER BY created_at, id LIMIT 1
            """,
            (
                source_record_id,
                identity_subject_id,
                claim.field_name,
                claimed_json,
                claim.source_kind.value,
                claim.evidence_method.value,
                claim.directness.value,
                claim.resolution_state.value,
                claim.claim_role.value,
            ),
        ).fetchone()
        if existing is not None:
            return existing["id"]
        return self.knowledge_base.append_field_claim(
            source_record_id,
            identity_subject_id,
            claim.field_name,
            claim.value,
            source_kind=claim.source_kind,
            evidence_method=claim.evidence_method,
            directness=claim.directness,
            resolution_state=claim.resolution_state,
            claim_role=claim.claim_role,
        )

    def _proven_card(self, external_identifier_id: str) -> Optional[str]:
        row = self.knowledge_base.connection.execute(
            """
            SELECT canonical_card_id FROM identifier_link
            WHERE external_identifier_id = ? AND resolution_state = 'PROVEN'
            """,
            (external_identifier_id,),
        ).fetchone()
        return None if row is None else row["canonical_card_id"]

    def _identity_resolution(
        self,
        identity_subject_id: str,
        observation: NormalizedObservation,
        canonical_card_id: Optional[str],
    ) -> str:
        resolution_state = (
            ResolutionState.PROVEN
            if canonical_card_id is not None and observation.exact_identity_eligible
            else ResolutionState.UNKNOWN
        )
        resolved_card_id = (
            canonical_card_id if resolution_state == ResolutionState.PROVEN else None
        )
        unresolved_json = _canonical_json(
            []
            if resolution_state == ResolutionState.PROVEN
            else sorted(set(observation.unresolved_dimensions))
        )
        existing = self.knowledge_base.connection.execute(
            """
            SELECT id FROM identity_resolution
            WHERE identity_subject_id = ?
              AND resolution_state = ?
              AND canonical_card_id IS ?
              AND unresolved_dimensions_json = ?
              AND conflicts_json = '[]'
            ORDER BY created_at, id LIMIT 1
            """,
            (
                identity_subject_id,
                resolution_state.value,
                resolved_card_id,
                unresolved_json,
            ),
        ).fetchone()
        if existing is not None:
            return existing["id"]
        previous = self.knowledge_base.connection.execute(
            """
            SELECT id FROM identity_resolution
            WHERE identity_subject_id = ? ORDER BY created_at DESC, id DESC LIMIT 1
            """,
            (identity_subject_id,),
        ).fetchone()
        return self.knowledge_base.create_identity_resolution(
            identity_subject_id,
            resolution_state,
            canonical_card_id=resolved_card_id,
            unresolved_dimensions=(
                ()
                if resolution_state == ResolutionState.PROVEN
                else tuple(sorted(set(observation.unresolved_dimensions)))
            ),
            supersedes_resolution_id=(None if previous is None else previous["id"]),
        )

    def ingest(
        self,
        record: RawSourceRecord,
        observations: Sequence[NormalizedObservation],
        diagnostics: ShadowDiagnostics,
    ) -> None:
        """Persist a raw record and every independently sealed typed fact."""

        source_system_id = self.knowledge_base.create_source_system(
            record.source_code, record.source_name, record.source_role
        )
        external_object_id = self.knowledge_base.create_external_object(
            source_system_id,
            record.object_type,
            record.external_native_id or record.source_native_record_id,
        )
        source_record_id = self.knowledge_base.append_source_record(
            source_system_id,
            record.source_native_record_id,
            record.payload,
            retrieved_at=record.retrieved_at,
            source_updated_at=record.source_updated_at,
            external_object_id=external_object_id,
        )

        for observation in observations:
            if (
                observation.observation_type == ObservationType.SALE_TRANSACTION
                and not observation.genuine_sale_evidence
            ):
                raise KnowledgeBaseError(
                    "sidecar sale transactions require explicit completed-sale evidence"
                )
            upstream_market_system_id = None
            if observation.upstream_market_code is not None:
                upstream_market_system_id = self.knowledge_base.create_source_system(
                    observation.upstream_market_code,
                    observation.upstream_market_name
                    or observation.upstream_market_code,
                    "MARKET",
                )

            external_identifier_id = self.knowledge_base.add_external_identifier(
                external_object_id,
                observation.identity_namespace,
                observation.identity_identifier_value,
            )
            proven_card_id = self._proven_card(external_identifier_id)
            if not observation.exact_identity_eligible:
                proven_card_id = None
            identity_subject_id = self._identity_subject(
                source_record_id, external_object_id, observation
            )
            for claim in observation.claims:
                self._append_claim_once(source_record_id, identity_subject_id, claim)
            identity_resolution_id = self._identity_resolution(
                identity_subject_id, observation, proven_card_id
            )

            idempotency_key = _observation_key(
                source_system_id, source_record_id, observation
            )
            existing = self.knowledge_base.connection.execute(
                """
                SELECT id, canonical_card_id FROM market_observation
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if (
                existing is not None
                and existing["canonical_card_id"] is not None
                and proven_card_id is not None
                and existing["canonical_card_id"] != proven_card_id
            ):
                raise IdempotencyConflict(
                    "replay exact identity conflicts with the immutable observation"
                )
            canonical_for_observation = (
                existing["canonical_card_id"]
                if existing is not None
                else proven_card_id
            )
            observation_id = self.knowledge_base.append_market_observation(
                observation.observation_type,
                source_system_id,
                observation.source_native_record_id,
                observed_at=observation.observed_at,
                ingested_at=self.clock(),
                source_updated_at=observation.source_updated_at,
                source_record_id=source_record_id,
                upstream_market_system_id=upstream_market_system_id,
                canonical_card_id=canonical_for_observation,
                event_at=observation.event_at,
                event_time_precision=observation.event_time_precision,
                fact=observation.fact,
                prices=observation.prices,
                idempotency_key=idempotency_key,
            )

            exact_link = bool(
                proven_card_id is not None
                and canonical_for_observation == proven_card_id
            )
            self.knowledge_base.link_observation_identity(
                observation_id,
                identity_resolution_id,
                canonical_card_id=(proven_card_id if exact_link else None),
                link_role=("RESOLVED_AS" if exact_link else "SUBJECT"),
            )
            if existing is not None:
                diagnostics.observations_replayed += 1
                continue
            diagnostics.observations_accepted += 1
            if exact_link:
                diagnostics.exact_identities_linked += 1
            else:
                diagnostics.unresolved_identities_retained += 1
            if observation.observation_type == ObservationType.PROVIDER_METRIC_OBSERVATION:
                diagnostics.provider_metrics_stored += 1
            elif observation.observation_type == ObservationType.SALE_TRANSACTION:
                diagnostics.sale_transactions_stored += 1
