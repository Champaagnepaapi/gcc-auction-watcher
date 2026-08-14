"""Persistence adapter from normalized sidecar facts to the P0 repository."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
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
    if observation.observation_type == ObservationType.SALE_TRANSACTION:
        identity = {
            "sidecar_version": 2,
            "source_system_id": source_system_id,
            "source_native_record_id": observation.source_native_record_id,
            "observation_type": observation.observation_type.value,
            "economic_sale": _sale_signature(observation),
        }
    else:
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


def _instant(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise KnowledgeBaseError(f"{field} must be a timezone-aware timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise KnowledgeBaseError(f"{field} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise KnowledgeBaseError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _sale_signature(observation: NormalizedObservation) -> Mapping[str, Any]:
    if observation.event_at is None:
        raise KnowledgeBaseError("completed sale requires an explicit event timestamp")
    final_prices = tuple(
        sorted(
            (
                component.component_type,
                component.amount_minor,
                component.currency,
            )
            for component in observation.prices
            if component.component_type != "SHIPPING"
        )
    )
    if len(final_prices) != 1 or any(value is None for value in final_prices[0]):
        raise KnowledgeBaseError("completed sale requires one explicit final price")
    return {
        "event_at": _instant(observation.event_at, field="sale event_at"),
        "final_prices": final_prices,
    }


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

    def _checkpoint(
        self, name: str, observation: NormalizedObservation
    ) -> None:
        """Failure-injection seam used to prove the outer ingest savepoint."""

    def _validate_sale(self, observation: NormalizedObservation) -> None:
        if not observation.genuine_sale_evidence:
            raise KnowledgeBaseError(
                "sidecar sale transactions require explicit completed-sale evidence"
            )
        sale_at = _instant(observation.event_at, field="sale event_at")
        observed_at = _instant(observation.observed_at, field="observed_at")
        if sale_at > observed_at:
            raise KnowledgeBaseError("sale event cannot be later than observation")
        fact_sale_at = observation.fact.get("sale_occurred_at")
        if _instant(fact_sale_at, field="sale_occurred_at") != sale_at:
            raise KnowledgeBaseError("sale fact timestamp contradicts event timestamp")
        if observation.source_updated_at is not None:
            updated_at = _instant(
                observation.source_updated_at, field="source_updated_at"
            )
            if not sale_at <= updated_at <= observed_at:
                raise KnowledgeBaseError("sale event contradicts source chronology")
        _sale_signature(observation)

    def _existing_finalized_sale(
        self,
        source_system_id: str,
        observation: NormalizedObservation,
    ) -> Optional[Mapping[str, Any]]:
        rows = self.knowledge_base.connection.execute(
            """
            SELECT observation.id, observation.event_at,
                   observation.canonical_card_id
            FROM market_observation AS observation
            JOIN sale_transaction AS sale
              ON sale.observation_id = observation.id
            WHERE observation.source_system_id = ?
              AND observation.source_native_record_id = ?
              AND observation.observation_type = 'SALE_TRANSACTION'
              AND observation.lifecycle_state = 'SEALED'
            ORDER BY observation.created_at, observation.id
            """,
            (source_system_id, observation.source_native_record_id),
        ).fetchall()
        if not rows:
            return None
        expected = _sale_signature(observation)
        matches = []
        for row in rows:
            prices = self.knowledge_base.connection.execute(
                """
                SELECT component_type, amount_minor, currency
                FROM price_component
                WHERE observation_id = ?
                  AND component_type <> 'SHIPPING'
                ORDER BY component_type
                """,
                (row["id"],),
            ).fetchall()
            existing = {
                "event_at": _instant(row["event_at"], field="stored sale event_at"),
                "final_prices": tuple(
                    (price["component_type"], price["amount_minor"], price["currency"])
                    for price in prices
                ),
            }
            if existing == expected:
                matches.append(row)
        if len(rows) == 1 and len(matches) == 1:
            return matches[0]
        raise IdempotencyConflict(
            "finalized listing already has a contradictory or duplicate economic sale"
        )

    def ingest(
        self,
        record: RawSourceRecord,
        observations: Sequence[NormalizedObservation],
        diagnostics: ShadowDiagnostics,
    ) -> None:
        """Persist a raw record and every independently sealed typed fact."""

        deltas = {
            "observations_replayed": 0,
            "duplicate_sale_replays": 0,
            "observations_accepted": 0,
            "exact_identities_linked": 0,
            "unresolved_identities_retained": 0,
            "provider_metrics_stored": 0,
            "sale_transactions_stored": 0,
        }
        with self.knowledge_base._transaction():
            self._ingest_atomic(record, observations, deltas)
        for field_name, value in deltas.items():
            setattr(diagnostics, field_name, getattr(diagnostics, field_name) + value)

    def _ingest_atomic(
        self,
        record: RawSourceRecord,
        observations: Sequence[NormalizedObservation],
        deltas: dict[str, int],
    ) -> None:
        """Run one record and all derived facts under the caller's savepoint."""

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
            if observation.observation_type == ObservationType.SALE_TRANSACTION:
                self._validate_sale(observation)
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

            existing_sale = None
            if observation.observation_type == ObservationType.SALE_TRANSACTION:
                existing_sale = self._existing_finalized_sale(
                    source_system_id, observation
                )

            idempotency_key = _observation_key(
                source_system_id, source_record_id, observation
            )
            existing = existing_sale or self.knowledge_base.connection.execute(
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
            if existing_sale is not None:
                observation_id = existing_sale["id"]
            else:
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
            self._checkpoint("after_observation_seal", observation)

            exact_link = bool(
                proven_card_id is not None
                and canonical_for_observation == proven_card_id
            )
            self._checkpoint("before_identity_link", observation)
            self.knowledge_base.link_observation_identity(
                observation_id,
                identity_resolution_id,
                canonical_card_id=(proven_card_id if exact_link else None),
                link_role=("RESOLVED_AS" if exact_link else "SUBJECT"),
            )
            if existing is not None:
                deltas["observations_replayed"] += 1
                if existing_sale is not None:
                    deltas["duplicate_sale_replays"] += 1
                continue
            deltas["observations_accepted"] += 1
            if exact_link:
                deltas["exact_identities_linked"] += 1
            else:
                deltas["unresolved_identities_retained"] += 1
            if observation.observation_type == ObservationType.PROVIDER_METRIC_OBSERVATION:
                deltas["provider_metrics_stored"] += 1
            elif observation.observation_type == ObservationType.SALE_TRANSACTION:
                deltas["sale_transactions_stored"] += 1
