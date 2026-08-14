"""Repository API for the isolated SQLite card knowledge base."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional, Sequence, Tuple, Union

from .domain import (
    ClaimRole,
    Directness,
    EvidenceMethod,
    InclusionState,
    ObservationRelationshipType,
    ObservationType,
    PriceKnowledge,
    ResolutionState,
    SourceKind,
)
from .migrations import apply_migrations, connect_database


class KnowledgeBaseError(RuntimeError):
    pass


class IdempotencyConflict(KnowledgeBaseError):
    pass


class ProvenanceError(KnowledgeBaseError):
    pass


class VariantError(KnowledgeBaseError):
    pass


@dataclass(frozen=True)
class CandidateInput:
    canonical_card_id: str
    rank: int
    support_score: Optional[str] = None
    evidence_summary: Optional[str] = None


@dataclass(frozen=True)
class ResolvedField:
    field_name: str
    resolution_state: ResolutionState
    value: Any = None
    based_on_claim_id: Optional[str] = None
    resolution_id: Optional[str] = None


@dataclass(frozen=True)
class PriceComponent:
    component_type: str
    amount_minor: Optional[int]
    currency: Optional[str]
    knowledge_state: PriceKnowledge = PriceKnowledge.KNOWN
    inclusion_state: InclusionState = InclusionState.UNKNOWN

    def __post_init__(self) -> None:
        allowed = {
            "ITEM_PRICE",
            "HAMMER_PRICE",
            "ACCEPTED_OFFER",
            "BUYER_PREMIUM",
            "SHIPPING",
            "TAX",
            "TOTAL",
        }
        if self.component_type not in allowed:
            raise ValueError(f"unsupported price component: {self.component_type}")
        is_known = self.knowledge_state == PriceKnowledge.KNOWN
        if is_known != (self.amount_minor is not None and self.currency is not None):
            raise ValueError(
                "known prices require amount/currency; unknown prices preserve neither"
            )
        if self.amount_minor is not None and self.amount_minor < 0:
            raise ValueError("price amounts cannot be negative")
        if self.currency is not None and len(self.currency) != 3:
            raise ValueError("currency must be a three-letter code")


@dataclass(frozen=True)
class FXNormalization:
    component_type: str
    original_amount_minor: int
    original_currency: str
    fx_rate_decimal: str
    rate_source: str
    rate_effective_date: str
    target_currency: str
    target_amount_minor: int
    rate_observation_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.original_currency == self.target_currency:
            raise ValueError("FX normalization requires different currencies")
        if len(self.original_currency) != 3 or len(self.target_currency) != 3:
            raise ValueError("currency must be a three-letter code")
        if self.original_amount_minor < 0 or self.target_amount_minor < 0:
            raise ValueError("FX amounts cannot be negative")
        if Decimal(self.fx_rate_decimal) <= 0:
            raise ValueError("FX rate must be positive")


_FACT_COLUMNS: Dict[ObservationType, Tuple[str, Tuple[str, ...], Mapping[str, Any]]] = {
    ObservationType.SALE_TRANSACTION: (
        "sale_transaction",
        ("listing_started_at", "sale_occurred_at", "transaction_status"),
        {"listing_started_at": None, "sale_occurred_at": None, "transaction_status": "UNKNOWN"},
    ),
    ObservationType.LISTING_SNAPSHOT: (
        "listing_snapshot",
        ("listing_started_at", "snapshot_status", "quantity"),
        {"listing_started_at": None, "snapshot_status": "UNKNOWN", "quantity": None},
    ),
    ObservationType.PROVIDER_METRIC_OBSERVATION: (
        "provider_metric_observation",
        (
            "metric_name",
            "metric_value_minor",
            "currency",
            "window_started_at",
            "window_ended_at",
            "sample_size",
        ),
        {
            "metric_value_minor": None,
            "currency": None,
            "window_started_at": None,
            "window_ended_at": None,
            "sample_size": None,
        },
    ),
    ObservationType.POPULATION_OBSERVATION: (
        "population_observation",
        ("grader", "grade", "qualifier", "population_count"),
        {"qualifier": None},
    ),
    ObservationType.FX_RATE_OBSERVATION: (
        "fx_rate_observation",
        (
            "base_currency",
            "quote_currency",
            "rate_decimal",
            "effective_date",
            "rate_source",
        ),
        {},
    ),
}

_TIMESTAMP_FACT_FIELDS = {
    "listing_started_at",
    "sale_occurred_at",
    "window_started_at",
    "window_ended_at",
}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _timestamp(value: Union[str, datetime], *, field: str) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} must include a timezone")
        return value.isoformat(timespec="microseconds")
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a timezone-aware timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{field} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return value


def _optional_timestamp(value: Any, *, field: str) -> Optional[str]:
    if value is None:
        return None
    return _timestamp(value, field=field)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _payload_hash(payload: Any) -> str:
    if isinstance(payload, bytes):
        content = payload
    elif isinstance(payload, str):
        content = payload.encode("utf-8")
    else:
        content = _canonical_json(payload).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


class KnowledgeBase:
    """Explicit, local repository boundary for P0 knowledge-base data."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    @classmethod
    def open(cls, path: Union[str, Path] = ":memory:") -> "KnowledgeBase":
        connection = connect_database(path)
        try:
            apply_migrations(connection)
        except Exception:
            connection.close()
            raise
        return cls(connection)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "KnowledgeBase":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        nested = self.connection.in_transaction
        if not nested:
            self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            if not nested and self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise
        else:
            if not nested:
                self.connection.execute("COMMIT")

    def schema_versions(self) -> Sequence[int]:
        return [
            row[0]
            for row in self.connection.execute(
                "SELECT version FROM schema_migration ORDER BY version"
            )
        ]

    def create_source_system(self, code: str, name: str, system_role: str) -> str:
        existing = self.connection.execute(
            "SELECT id, name, system_role FROM source_system WHERE code = ?", (code,)
        ).fetchone()
        if existing:
            if existing["name"] != name or existing["system_role"] != system_role:
                raise IdempotencyConflict(f"source system {code!r} already differs")
            return existing["id"]
        source_id = _new_id("source")
        self.connection.execute(
            """
            INSERT INTO source_system(id, code, name, system_role, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (source_id, code, name, system_role, _now()),
        )
        return source_id

    def create_external_object(
        self,
        source_system_id: str,
        object_type: str,
        source_native_id: str,
        *,
        upstream_market_system_id: Optional[str] = None,
        upstream_native_id: Optional[str] = None,
    ) -> str:
        existing = self.connection.execute(
            """
            SELECT id, upstream_market_system_id, upstream_native_id
            FROM external_object
            WHERE source_system_id = ? AND object_type = ? AND source_native_id = ?
            """,
            (source_system_id, object_type, source_native_id),
        ).fetchone()
        if existing:
            if (
                existing["upstream_market_system_id"] != upstream_market_system_id
                or existing["upstream_native_id"] != upstream_native_id
            ):
                raise IdempotencyConflict("external object lineage already differs")
            return existing["id"]
        object_id = _new_id("extobj")
        self.connection.execute(
            """
            INSERT INTO external_object(
                id, source_system_id, object_type, source_native_id,
                upstream_market_system_id, upstream_native_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                object_id,
                source_system_id,
                object_type,
                source_native_id,
                upstream_market_system_id,
                upstream_native_id,
                _now(),
            ),
        )
        return object_id

    def add_external_identifier(
        self, external_object_id: str, namespace: str, identifier_value: str
    ) -> str:
        existing = self.connection.execute(
            """
            SELECT id FROM external_identifier
            WHERE external_object_id = ? AND namespace = ? AND identifier_value = ?
            """,
            (external_object_id, namespace, identifier_value),
        ).fetchone()
        if existing:
            return existing["id"]
        identifier_id = _new_id("extid")
        self.connection.execute(
            """
            INSERT INTO external_identifier(
                id, external_object_id, namespace, identifier_value, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (identifier_id, external_object_id, namespace, identifier_value, _now()),
        )
        return identifier_id

    def link_identifier(
        self,
        external_identifier_id: str,
        resolution_state: ResolutionState,
        *,
        canonical_card_id: Optional[str] = None,
    ) -> str:
        link_id = _new_id("idlink")
        self.connection.execute(
            """
            INSERT INTO identifier_link(
                id, external_identifier_id, canonical_card_id,
                resolution_state, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                link_id,
                external_identifier_id,
                canonical_card_id,
                resolution_state.value,
                _now(),
            ),
        )
        return link_id

    def append_source_record(
        self,
        source_system_id: str,
        source_native_record_id: str,
        payload: Any,
        *,
        retrieved_at: Union[str, datetime],
        source_updated_at: Optional[Union[str, datetime]] = None,
        external_object_id: Optional[str] = None,
    ) -> str:
        payload_sha256 = _payload_hash(payload)
        existing = self.connection.execute(
            """
            SELECT id FROM source_record
            WHERE source_system_id = ?
              AND source_native_record_id = ?
              AND payload_sha256 = ?
            """,
            (source_system_id, source_native_record_id, payload_sha256),
        ).fetchone()
        if existing:
            return existing["id"]
        record_id = _new_id("srecord")
        created_at = _now()
        self.connection.execute(
            """
            INSERT INTO source_record(
                id, source_system_id, external_object_id,
                source_native_record_id, payload_sha256, retrieved_at,
                source_updated_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                source_system_id,
                external_object_id,
                source_native_record_id,
                payload_sha256,
                _timestamp(retrieved_at, field="retrieved_at"),
                _optional_timestamp(source_updated_at, field="source_updated_at"),
                created_at,
            ),
        )
        return record_id

    def create_canonical_set(
        self, canonical_key: str, name: str, *, release_date: Optional[str] = None
    ) -> str:
        existing = self.connection.execute(
            "SELECT id, name, release_date FROM canonical_set WHERE canonical_key = ?",
            (canonical_key,),
        ).fetchone()
        if existing:
            if existing["name"] != name or existing["release_date"] != release_date:
                raise IdempotencyConflict("canonical set key already differs")
            return existing["id"]
        set_id = _new_id("set")
        self.connection.execute(
            """
            INSERT INTO canonical_set(
                id, canonical_key, name, release_date, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (set_id, canonical_key, name, release_date, _now()),
        )
        return set_id

    def create_card_family(
        self, canonical_set_id: str, collector_number: str, family_name: str
    ) -> str:
        existing = self.connection.execute(
            """
            SELECT id FROM card_family
            WHERE canonical_set_id = ? AND collector_number = ? AND family_name = ?
            """,
            (canonical_set_id, collector_number, family_name),
        ).fetchone()
        if existing:
            return existing["id"]
        family_id = _new_id("family")
        self.connection.execute(
            """
            INSERT INTO card_family(
                id, canonical_set_id, collector_number, family_name, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (family_id, canonical_set_id, collector_number, family_name, _now()),
        )
        return family_id

    def create_localized_card(
        self,
        card_family_id: str,
        language_code: str,
        localized_name: str,
        *,
        localized_set_name: Optional[str] = None,
    ) -> str:
        existing = self.connection.execute(
            """
            SELECT id, localized_name, localized_set_name FROM localized_card
            WHERE card_family_id = ? AND language_code = ?
            """,
            (card_family_id, language_code),
        ).fetchone()
        if existing:
            if (
                existing["localized_name"] != localized_name
                or existing["localized_set_name"] != localized_set_name
            ):
                raise IdempotencyConflict("localized card already differs")
            return existing["id"]
        localized_id = _new_id("localized")
        self.connection.execute(
            """
            INSERT INTO localized_card(
                id, card_family_id, language_code, localized_name,
                localized_set_name, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                localized_id,
                card_family_id,
                language_code,
                localized_name,
                localized_set_name,
                _now(),
            ),
        )
        return localized_id

    def create_variant_profile(
        self, assignments: Mapping[str, str], *, label: Optional[str] = None
    ) -> str:
        if not assignments:
            raise VariantError("a variant profile requires at least one dimension")
        normalized = sorted((str(key), str(value)) for key, value in assignments.items())
        if len({key for key, _ in normalized}) != len(normalized):
            raise VariantError("a variant dimension may be assigned only once")
        fingerprint = _sha256(normalized)
        existing = self.connection.execute(
            """
            SELECT id, locked_at FROM variant_profile
            WHERE fingerprint_sha256 = ?
            """,
            (fingerprint,),
        ).fetchone()
        if existing:
            if existing["locked_at"] is None:
                raise VariantError("an incomplete variant profile already exists")
            return existing["id"]

        resolved: list[Tuple[str, str]] = []
        for dimension_code, value_code in normalized:
            row = self.connection.execute(
                """
                SELECT d.id AS dimension_id, v.id AS value_id
                FROM variant_dimension d
                JOIN variant_value v ON v.dimension_id = d.id
                WHERE d.code = ? AND v.code = ?
                """,
                (dimension_code, value_code),
            ).fetchone()
            if row is None:
                raise VariantError(
                    f"unknown variant assignment {dimension_code}={value_code}"
                )
            resolved.append((row["dimension_id"], row["value_id"]))

        profile_id = _new_id("vprofile")
        with self._transaction():
            created_at = _now()
            self.connection.execute(
                """
                INSERT INTO variant_profile(
                    id, fingerprint_sha256, label, created_at, locked_at
                ) VALUES (?, ?, ?, ?, NULL)
                """,
                (profile_id, fingerprint, label, created_at),
            )
            for dimension_id, value_id in resolved:
                self.connection.execute(
                    """
                    INSERT INTO variant_assignment(
                        profile_id, dimension_id, value_id, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (profile_id, dimension_id, value_id, created_at),
                )
            self.connection.execute(
                "UPDATE variant_profile SET locked_at = ? WHERE id = ?",
                (_now(), profile_id),
            )
        return profile_id

    def set_family_variant_applicability(
        self,
        card_family_id: str,
        dimension_code: str,
        applicability_state: str,
    ) -> str:
        dimension = self.connection.execute(
            "SELECT id FROM variant_dimension WHERE code = ?", (dimension_code,)
        ).fetchone()
        if dimension is None:
            raise VariantError(f"unknown variant dimension {dimension_code!r}")
        existing = self.connection.execute(
            """
            SELECT id, applicability_state FROM family_variant_applicability
            WHERE card_family_id = ? AND dimension_id = ?
            """,
            (card_family_id, dimension["id"]),
        ).fetchone()
        if existing:
            if existing["applicability_state"] != applicability_state:
                raise IdempotencyConflict("variant applicability already differs")
            return existing["id"]
        applicability_id = _new_id("vapp")
        self.connection.execute(
            """
            INSERT INTO family_variant_applicability(
                id, card_family_id, dimension_id, applicability_state, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                applicability_id,
                card_family_id,
                dimension["id"],
                applicability_state,
                _now(),
            ),
        )
        return applicability_id

    def allow_variant_profile(self, card_family_id: str, variant_profile_id: str) -> str:
        existing = self.connection.execute(
            """
            SELECT id FROM allowed_variant_combination
            WHERE card_family_id = ? AND variant_profile_id = ?
            """,
            (card_family_id, variant_profile_id),
        ).fetchone()
        if existing:
            return existing["id"]
        combination_id = _new_id("vcombo")
        self.connection.execute(
            """
            INSERT INTO allowed_variant_combination(
                id, card_family_id, variant_profile_id, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (combination_id, card_family_id, variant_profile_id, _now()),
        )
        return combination_id

    def create_canonical_card(
        self, localized_card_id: str, variant_profile_id: str
    ) -> str:
        row = self.connection.execute(
            """
            SELECT l.card_family_id, p.fingerprint_sha256
            FROM localized_card l
            JOIN variant_profile p ON p.id = ?
            WHERE l.id = ? AND p.locked_at IS NOT NULL
            """,
            (variant_profile_id, localized_card_id),
        ).fetchone()
        if row is None:
            raise VariantError("localized card or locked variant profile does not exist")
        allowed = self.connection.execute(
            """
            SELECT 1 FROM allowed_variant_combination
            WHERE card_family_id = ? AND variant_profile_id = ?
            """,
            (row["card_family_id"], variant_profile_id),
        ).fetchone()
        if allowed is None:
            raise VariantError("variant profile is not allowed for this card family")
        existing = self.connection.execute(
            """
            SELECT id FROM canonical_card
            WHERE localized_card_id = ? AND variant_profile_id = ?
            """,
            (localized_card_id, variant_profile_id),
        ).fetchone()
        if existing:
            return existing["id"]
        comparison_key = "cardcmp_" + _sha256(
            [localized_card_id, row["fingerprint_sha256"]]
        )
        card_id = _new_id("card")
        self.connection.execute(
            """
            INSERT INTO canonical_card(
                id, localized_card_id, variant_profile_id,
                exact_comparison_key, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (card_id, localized_card_id, variant_profile_id, comparison_key, _now()),
        )
        return card_id

    def comparison_domain_key(
        self,
        canonical_card_id: str,
        *,
        grader: Optional[str] = None,
        grade: Optional[str] = None,
        qualifier: Optional[str] = None,
    ) -> str:
        if (grader is None) != (grade is None):
            raise ValueError("grader and grade must be supplied together")
        if qualifier is not None and grader is None:
            raise ValueError("a qualifier requires a graded segment")
        row = self.connection.execute(
            "SELECT exact_comparison_key FROM canonical_card WHERE id = ?",
            (canonical_card_id,),
        ).fetchone()
        if row is None:
            raise KnowledgeBaseError("canonical card does not exist")
        return "segment_" + _sha256(
            {
                "canonical_print": row["exact_comparison_key"],
                "grader": grader,
                "grade": grade,
                "qualifier": qualifier,
            }
        )

    def add_card_alias(
        self,
        canonical_card_id: str,
        alias_text: str,
        *,
        source_system_id: Optional[str] = None,
        language_code: Optional[str] = None,
    ) -> str:
        existing = self.connection.execute(
            """
            SELECT id FROM card_alias
            WHERE canonical_card_id = ? AND source_system_id IS ?
              AND alias_text = ? AND language_code IS ?
            """,
            (canonical_card_id, source_system_id, alias_text, language_code),
        ).fetchone()
        if existing:
            return existing["id"]
        alias_id = _new_id("alias")
        self.connection.execute(
            """
            INSERT INTO card_alias(
                id, canonical_card_id, source_system_id, alias_text,
                language_code, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                alias_id,
                canonical_card_id,
                source_system_id,
                alias_text,
                language_code,
                _now(),
            ),
        )
        return alias_id

    def create_collectible_instance(
        self,
        canonical_card_id: str,
        *,
        grader: Optional[str] = None,
        grade: Optional[str] = None,
        qualifier: Optional[str] = None,
        subgrades: Optional[Mapping[str, Any]] = None,
        certification_identifier_id: Optional[str] = None,
    ) -> str:
        instance_id = _new_id("instance")
        self.connection.execute(
            """
            INSERT INTO collectible_instance(
                id, canonical_card_id, grader, grade, qualifier,
                subgrades_json, certification_identifier_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                canonical_card_id,
                grader,
                grade,
                qualifier,
                _canonical_json(subgrades) if subgrades is not None else None,
                certification_identifier_id,
                _now(),
            ),
        )
        return instance_id

    def create_identity_subject(
        self,
        subject_type: str,
        *,
        source_record_id: Optional[str] = None,
        external_object_id: Optional[str] = None,
        subject_label: Optional[str] = None,
    ) -> str:
        subject_id = _new_id("subject")
        self.connection.execute(
            """
            INSERT INTO identity_subject(
                id, subject_type, source_record_id, external_object_id,
                subject_label, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                subject_id,
                subject_type,
                source_record_id,
                external_object_id,
                subject_label,
                _now(),
            ),
        )
        return subject_id

    def create_identity_resolution(
        self,
        identity_subject_id: str,
        resolution_state: ResolutionState,
        *,
        canonical_card_id: Optional[str] = None,
        candidates: Sequence[CandidateInput] = (),
        unresolved_dimensions: Sequence[str] = (),
        conflicts: Sequence[str] = (),
        supersedes_resolution_id: Optional[str] = None,
    ) -> str:
        if resolution_state in {ResolutionState.UNKNOWN, ResolutionState.CONFLICT}:
            if canonical_card_id is not None:
                raise ProvenanceError("unresolved/conflicting identity cannot be forced")
        if resolution_state == ResolutionState.PROVEN and canonical_card_id is None:
            raise ProvenanceError("proven identity requires a canonical card")
        candidate_ids = [candidate.canonical_card_id for candidate in candidates]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ProvenanceError("identity candidates must be unique")
        resolution_id = _new_id("ires")
        with self._transaction():
            self.connection.execute(
                """
                INSERT INTO identity_resolution(
                    id, identity_subject_id, resolution_state, canonical_card_id,
                    unresolved_dimensions_json, conflicts_json,
                    supersedes_resolution_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolution_id,
                    identity_subject_id,
                    resolution_state.value,
                    canonical_card_id,
                    _canonical_json(list(unresolved_dimensions)),
                    _canonical_json(list(conflicts)),
                    supersedes_resolution_id,
                    _now(),
                ),
            )
            for candidate in candidates:
                self.connection.execute(
                    """
                    INSERT INTO identity_candidate(
                        id, identity_resolution_id, canonical_card_id,
                        candidate_rank, support_score, evidence_summary, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _new_id("candidate"),
                        resolution_id,
                        candidate.canonical_card_id,
                        candidate.rank,
                        candidate.support_score,
                        candidate.evidence_summary,
                        _now(),
                    ),
                )
        return resolution_id

    def append_field_claim(
        self,
        source_record_id: str,
        identity_subject_id: str,
        field_name: str,
        value: Any,
        *,
        source_kind: SourceKind,
        evidence_method: EvidenceMethod,
        directness: Directness,
        resolution_state: ResolutionState,
        claim_role: ClaimRole = ClaimRole.EVIDENCE,
    ) -> str:
        if claim_role == ClaimRole.REQUEST_TARGET and resolution_state != ResolutionState.UNKNOWN:
            raise ProvenanceError("a request target cannot become proof")
        claim_id = _new_id("claim")
        self.connection.execute(
            """
            INSERT INTO field_claim(
                id, source_record_id, identity_subject_id, field_name,
                claimed_value_json, source_kind, evidence_method, directness,
                resolution_state, claim_role, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim_id,
                source_record_id,
                identity_subject_id,
                field_name,
                _canonical_json(value),
                source_kind.value,
                evidence_method.value,
                directness.value,
                resolution_state.value,
                claim_role.value,
                _now(),
            ),
        )
        return claim_id

    def resolve_field(
        self,
        identity_subject_id: str,
        field_name: str,
        resolution_state: ResolutionState,
        *,
        value: Any = None,
        based_on_claim_id: Optional[str] = None,
        supersedes_resolution_id: Optional[str] = None,
    ) -> str:
        if resolution_state in {ResolutionState.PROVEN, ResolutionState.SUPPORTED}:
            if based_on_claim_id is None:
                raise ProvenanceError("positive field resolution requires evidence")
            claim = self.connection.execute(
                """
                SELECT claim_role, identity_subject_id, field_name
                FROM field_claim WHERE id = ?
                """,
                (based_on_claim_id,),
            ).fetchone()
            if claim is None:
                raise ProvenanceError("evidence claim does not exist")
            if claim["claim_role"] == ClaimRole.REQUEST_TARGET.value:
                raise ProvenanceError("a request target is not evidence")
            if (
                claim["identity_subject_id"] != identity_subject_id
                or claim["field_name"] != field_name
            ):
                raise ProvenanceError("evidence must match the subject and field")
        if resolution_state == ResolutionState.UNKNOWN and value is not None:
            raise ProvenanceError("an unknown field cannot have a resolved default")
        resolution_id = _new_id("fres")
        self.connection.execute(
            """
            INSERT INTO field_resolution(
                id, identity_subject_id, field_name, resolved_value_json,
                resolution_state, based_on_claim_id,
                supersedes_resolution_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolution_id,
                identity_subject_id,
                field_name,
                None if value is None else _canonical_json(value),
                resolution_state.value,
                based_on_claim_id,
                supersedes_resolution_id,
                _now(),
            ),
        )
        return resolution_id

    def latest_field_resolution(
        self, identity_subject_id: str, field_name: str
    ) -> ResolvedField:
        row = self.connection.execute(
            """
            SELECT id, resolved_value_json, resolution_state, based_on_claim_id
            FROM field_resolution
            WHERE identity_subject_id = ? AND field_name = ?
            ORDER BY rowid DESC LIMIT 1
            """,
            (identity_subject_id, field_name),
        ).fetchone()
        if row is None:
            return ResolvedField(field_name, ResolutionState.UNKNOWN)
        value = (
            json.loads(row["resolved_value_json"])
            if row["resolved_value_json"] is not None
            else None
        )
        return ResolvedField(
            field_name=field_name,
            resolution_state=ResolutionState(row["resolution_state"]),
            value=value,
            based_on_claim_id=row["based_on_claim_id"],
            resolution_id=row["id"],
        )

    def append_market_observation(
        self,
        observation_type: ObservationType,
        source_system_id: str,
        source_native_record_id: str,
        *,
        observed_at: Union[str, datetime],
        fact: Mapping[str, Any],
        canonical_card_id: Optional[str] = None,
        source_record_id: Optional[str] = None,
        upstream_market_system_id: Optional[str] = None,
        upstream_event_object_id: Optional[str] = None,
        event_at: Optional[Union[str, datetime]] = None,
        event_time_precision: str = "UNKNOWN",
        ingested_at: Optional[Union[str, datetime]] = None,
        source_updated_at: Optional[Union[str, datetime]] = None,
        revision_of_observation_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        prices: Sequence[PriceComponent] = (),
        fx_normalizations: Sequence[FXNormalization] = (),
    ) -> str:
        observed = _timestamp(observed_at, field="observed_at")
        event = _optional_timestamp(event_at, field="event_at")
        source_updated = _optional_timestamp(
            source_updated_at, field="source_updated_at"
        )
        ingested = (
            _timestamp(ingested_at, field="ingested_at")
            if ingested_at is not None
            else _now()
        )
        normalized_fact = self._normalize_fact(observation_type, fact)
        price_payload = sorted(
            (
                {
                    **asdict(component),
                    "knowledge_state": component.knowledge_state.value,
                    "inclusion_state": component.inclusion_state.value,
                }
                for component in prices
            ),
            key=lambda component: component["component_type"],
        )
        fx_payload = sorted(
            (asdict(normalization) for normalization in fx_normalizations),
            key=lambda normalization: (
                normalization["component_type"],
                normalization["target_currency"],
            ),
        )
        content = {
            "observation_type": observation_type.value,
            "source_system_id": source_system_id,
            "source_native_record_id": source_native_record_id,
            "canonical_card_id": canonical_card_id,
            "source_record_id": source_record_id,
            "upstream_market_system_id": upstream_market_system_id,
            "upstream_event_object_id": upstream_event_object_id,
            "event_at": event,
            "event_time_precision": event_time_precision,
            "observed_at": observed,
            "source_updated_at": source_updated,
            "revision_of_observation_id": revision_of_observation_id,
            "fact": normalized_fact,
            "prices": price_payload,
            "fx_normalizations": fx_payload,
        }
        content_hash = _sha256(content)
        if idempotency_key is None:
            idempotency_key = "obskey_" + _sha256(
                {
                    "source_system_id": source_system_id,
                    "source_native_record_id": source_native_record_id,
                    "source_record_id": source_record_id,
                    "observation_type": observation_type.value,
                    "observed_at": observed,
                    "source_updated_at": source_updated,
                    "revision_of_observation_id": revision_of_observation_id,
                }
            )
        existing = self.connection.execute(
            """
            SELECT id, content_sha256 FROM market_observation
            WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()
        if existing:
            if existing["content_sha256"] != content_hash:
                raise IdempotencyConflict(
                    "idempotency key already represents different observation facts"
                )
            return existing["id"]

        observation_id = _new_id("observation")
        with self._transaction():
            self.connection.execute(
                """
                INSERT INTO market_observation(
                    id, observation_type, source_system_id,
                    upstream_market_system_id, source_record_id,
                    source_native_record_id, upstream_event_object_id,
                    canonical_card_id, idempotency_key, content_sha256,
                    event_at, event_time_precision, observed_at, ingested_at,
                    source_updated_at, revision_of_observation_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_id,
                    observation_type.value,
                    source_system_id,
                    upstream_market_system_id,
                    source_record_id,
                    source_native_record_id,
                    upstream_event_object_id,
                    canonical_card_id,
                    idempotency_key,
                    content_hash,
                    event,
                    event_time_precision,
                    observed,
                    ingested,
                    source_updated,
                    revision_of_observation_id,
                    _now(),
                ),
            )
            self._insert_fact(observation_id, observation_type, normalized_fact)
            for component in prices:
                self.connection.execute(
                    """
                    INSERT INTO price_component(
                        id, observation_id, component_type, amount_minor,
                        currency, knowledge_state, inclusion_state, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _new_id("price"),
                        observation_id,
                        component.component_type,
                        component.amount_minor,
                        component.currency,
                        component.knowledge_state.value,
                        component.inclusion_state.value,
                        _now(),
                    ),
                )
            for normalization in fx_normalizations:
                if normalization.rate_observation_id is not None:
                    rate = self.connection.execute(
                        "SELECT observation_type FROM market_observation WHERE id = ?",
                        (normalization.rate_observation_id,),
                    ).fetchone()
                    if (
                        rate is None
                        or rate["observation_type"]
                        != ObservationType.FX_RATE_OBSERVATION.value
                    ):
                        raise KnowledgeBaseError(
                            "rate_observation_id must reference an FX rate observation"
                        )
                self.connection.execute(
                    """
                    INSERT INTO fx_normalization(
                        id, observation_id, component_type,
                        original_amount_minor, original_currency,
                        fx_rate_decimal, rate_observation_id, rate_source,
                        rate_effective_date, target_currency,
                        target_amount_minor, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _new_id("fxnorm"),
                        observation_id,
                        normalization.component_type,
                        normalization.original_amount_minor,
                        normalization.original_currency,
                        normalization.fx_rate_decimal,
                        normalization.rate_observation_id,
                        normalization.rate_source,
                        normalization.rate_effective_date,
                        normalization.target_currency,
                        normalization.target_amount_minor,
                        _now(),
                    ),
                )
            if revision_of_observation_id is not None:
                self._insert_observation_relationship(
                    observation_id,
                    revision_of_observation_id,
                    ObservationRelationshipType.REVISION_OF,
                )
        return observation_id

    def _normalize_fact(
        self, observation_type: ObservationType, fact: Mapping[str, Any]
    ) -> Dict[str, Any]:
        _, columns, defaults = _FACT_COLUMNS[observation_type]
        unknown = set(fact) - set(columns)
        if unknown:
            raise KnowledgeBaseError(
                f"unsupported {observation_type.value} fact fields: {sorted(unknown)}"
            )
        normalized = dict(defaults)
        normalized.update(fact)
        missing = [column for column in columns if column not in normalized]
        if missing:
            raise KnowledgeBaseError(
                f"missing {observation_type.value} fact fields: {missing}"
            )
        for field in _TIMESTAMP_FACT_FIELDS:
            if field in normalized:
                normalized[field] = _optional_timestamp(
                    normalized[field], field=field
                )
        return {column: normalized[column] for column in columns}

    def _insert_fact(
        self,
        observation_id: str,
        observation_type: ObservationType,
        fact: Mapping[str, Any],
    ) -> None:
        table, columns, _ = _FACT_COLUMNS[observation_type]
        column_sql = ", ".join(("observation_id",) + columns)
        placeholders = ", ".join("?" for _ in range(len(columns) + 1))
        self.connection.execute(
            f"INSERT INTO {table}({column_sql}) VALUES ({placeholders})",
            (observation_id,) + tuple(fact[column] for column in columns),
        )

    def add_observation_relationship(
        self,
        from_observation_id: str,
        to_observation_id: str,
        relationship_type: ObservationRelationshipType,
    ) -> str:
        existing = self.connection.execute(
            """
            SELECT id FROM observation_relationship
            WHERE from_observation_id = ? AND to_observation_id = ?
              AND relationship_type = ?
            """,
            (from_observation_id, to_observation_id, relationship_type.value),
        ).fetchone()
        if existing:
            return existing["id"]
        with self._transaction():
            return self._insert_observation_relationship(
                from_observation_id, to_observation_id, relationship_type
            )

    def _insert_observation_relationship(
        self,
        from_observation_id: str,
        to_observation_id: str,
        relationship_type: ObservationRelationshipType,
    ) -> str:
        relationship_id = _new_id("orel")
        self.connection.execute(
            """
            INSERT INTO observation_relationship(
                id, from_observation_id, to_observation_id,
                relationship_type, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                relationship_id,
                from_observation_id,
                to_observation_id,
                relationship_type.value,
                _now(),
            ),
        )
        return relationship_id

    def link_observation_identity(
        self,
        observation_id: str,
        identity_resolution_id: str,
        *,
        canonical_card_id: Optional[str] = None,
        link_role: str = "SUBJECT",
    ) -> str:
        existing = self.connection.execute(
            """
            SELECT id FROM observation_identity_link
            WHERE observation_id = ? AND identity_resolution_id = ?
              AND link_role = ?
            """,
            (observation_id, identity_resolution_id, link_role),
        ).fetchone()
        if existing:
            return existing["id"]
        link_id = _new_id("oilink")
        self.connection.execute(
            """
            INSERT INTO observation_identity_link(
                id, observation_id, identity_resolution_id,
                canonical_card_id, link_role, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                link_id,
                observation_id,
                identity_resolution_id,
                canonical_card_id,
                link_role,
                _now(),
            ),
        )
        return link_id

    def fetch_observation(self, observation_id: str) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT * FROM market_observation WHERE id = ?", (observation_id,)
        ).fetchone()
        if row is None:
            raise KnowledgeBaseError("observation does not exist")
        return row

    def price_components(self, observation_id: str) -> Sequence[sqlite3.Row]:
        return self.connection.execute(
            """
            SELECT * FROM price_component
            WHERE observation_id = ? ORDER BY component_type
            """,
            (observation_id,),
        ).fetchall()

    def observation_count(self) -> int:
        return self.connection.execute(
            "SELECT COUNT(*) FROM market_observation"
        ).fetchone()[0]
