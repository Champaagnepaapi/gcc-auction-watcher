"""Immutable catalogue identity snapshots for Robot KB.

This cache deliberately stops at *macro* card identity (language, card name,
set, local collector number and optional official denominator). It never creates
a ``canonical_card`` and never proves edition, finish or another commercial
microvariant. Those dimensions remain downstream fail-closed gates.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

from .repository import KnowledgeBase


TCGDEX_SOURCE_CODE = "tcgdex"
TCGDEX_SOURCE_NAME = "TCGdex"
TCGDEX_SOURCE_ROLE = "PROVIDER"

MATCHED = "MATCHED"
AMBIGUOUS = "AMBIGUOUS"
NO_MATCH = "NO_MATCH"
DENOMINATOR_CONFLICT = "DENOMINATOR_CONFLICT"
DENOMINATOR_UNPROVEN = "DENOMINATOR_UNPROVEN"


def _safe_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return re.sub(r"\s+", " ", text)


def _lookup_text(value: object) -> str:
    return _safe_text(value).casefold()


def _language(value: object) -> str:
    return _safe_text(value).casefold().replace("_", "-")


def _local_id(value: object) -> str:
    raw = _safe_text(value)
    if raw.isdigit():
        return str(int(raw))
    return raw.casefold()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _validate_timestamp(value: str) -> str:
    if not value:
        raise ValueError("observed_at is required")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed_at must include a timezone")
    return value


def _split_card_number(value: object) -> tuple[str, Optional[int]]:
    raw = _safe_text(value)
    numerator, separator, denominator = raw.partition("/")
    local = _local_id(numerator)
    if not local:
        raise ValueError("card number/localId is required")
    if not separator:
        return local, None
    if not denominator.strip().isdigit() or int(denominator.strip()) <= 0:
        raise ValueError("card-number denominator must be a positive integer")
    return local, int(denominator.strip())


def macro_lookup_key(
    *, language_code: str, card_name: str, set_name: str, local_id: str
) -> str:
    payload = {
        "language_code": _language(language_code),
        "card_name": _lookup_text(card_name),
        "set_name": _lookup_text(set_name),
        "local_id": _local_id(local_id),
    }
    if not all(payload.values()):
        raise ValueError("macro lookup coordinates must all be present")
    return _sha256(payload)


@dataclass(frozen=True)
class TCGdexMacroSnapshot:
    source_native_id: str
    language_code: str
    provider_set_id: str
    provider_set_name: str
    provider_card_name: str
    local_id: str
    observed_at: str
    official_card_count: Optional[int] = None
    variants: Optional[Mapping[str, Any]] = None

    def __post_init__(self) -> None:
        for label, value in (
            ("source_native_id", self.source_native_id),
            ("language_code", self.language_code),
            ("provider_set_id", self.provider_set_id),
            ("provider_set_name", self.provider_set_name),
            ("provider_card_name", self.provider_card_name),
            ("local_id", self.local_id),
        ):
            if not _safe_text(value):
                raise ValueError(f"{label} is required")
        if self.official_card_count is not None and self.official_card_count <= 0:
            raise ValueError("official_card_count must be positive")
        _validate_timestamp(self.observed_at)


@dataclass(frozen=True)
class TCGdexMacroCandidate:
    snapshot_id: str
    source_native_id: str
    language_code: str
    provider_set_id: str
    provider_set_name: str
    provider_card_name: str
    local_id: str
    official_card_count: Optional[int]
    variants: Optional[Mapping[str, Any]]
    observed_at: str


@dataclass(frozen=True)
class TCGdexMacroLookupResult:
    status: str
    candidate: Optional[TCGdexMacroCandidate] = None
    candidates: tuple[TCGdexMacroCandidate, ...] = ()

    @property
    def matched(self) -> bool:
        return self.status == MATCHED and self.candidate is not None

    @property
    def ambiguous(self) -> bool:
        return self.status == AMBIGUOUS


def _source_id(kb: KnowledgeBase) -> str:
    return kb.create_source_system(
        TCGDEX_SOURCE_CODE,
        TCGDEX_SOURCE_NAME,
        TCGDEX_SOURCE_ROLE,
    )


def store_tcgdex_macro_snapshot(
    kb: KnowledgeBase,
    snapshot: TCGdexMacroSnapshot,
) -> str:
    """Append a changed TCGdex macro snapshot; identical content is idempotent."""

    source_id = _source_id(kb)
    language = _language(snapshot.language_code)
    local_id = _local_id(snapshot.local_id)
    variants_json = (
        _canonical_json(snapshot.variants) if snapshot.variants is not None else None
    )
    fingerprint_payload = {
        "source_native_id": _safe_text(snapshot.source_native_id),
        "language_code": language,
        "provider_set_id": _safe_text(snapshot.provider_set_id),
        "provider_set_name": _safe_text(snapshot.provider_set_name),
        "provider_card_name": _safe_text(snapshot.provider_card_name),
        "local_id": local_id,
        "official_card_count": snapshot.official_card_count,
        "variants": snapshot.variants,
    }
    fingerprint = _sha256(fingerprint_payload)
    lookup_key = macro_lookup_key(
        language_code=language,
        card_name=snapshot.provider_card_name,
        set_name=snapshot.provider_set_name,
        local_id=local_id,
    )
    existing = kb.connection.execute(
        """
        SELECT id FROM catalog_identity_snapshot
        WHERE source_system_id = ? AND source_native_id = ?
          AND language_code = ? AND fingerprint_sha256 = ?
        """,
        (source_id, _safe_text(snapshot.source_native_id), language, fingerprint),
    ).fetchone()
    if existing is not None:
        return existing["id"]

    snapshot_id = f"catalog_{fingerprint[:24]}"
    kb.connection.execute(
        """
        INSERT INTO catalog_identity_snapshot(
            id, source_system_id, source_native_id, language_code,
            provider_set_id, provider_set_name, provider_card_name, local_id,
            official_card_count, variants_json, macro_lookup_key_sha256,
            fingerprint_sha256, observed_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            source_id,
            _safe_text(snapshot.source_native_id),
            language,
            _safe_text(snapshot.provider_set_id),
            _safe_text(snapshot.provider_set_name),
            _safe_text(snapshot.provider_card_name),
            local_id,
            snapshot.official_card_count,
            variants_json,
            lookup_key,
            fingerprint,
            _validate_timestamp(snapshot.observed_at),
            _validate_timestamp(snapshot.observed_at),
        ),
    )
    return snapshot_id


def _decode_candidate(row: Mapping[str, Any]) -> TCGdexMacroCandidate:
    variants: Optional[Mapping[str, Any]] = None
    raw_variants = row["variants_json"]
    if raw_variants:
        decoded = json.loads(raw_variants)
        if isinstance(decoded, Mapping):
            variants = decoded
    return TCGdexMacroCandidate(
        snapshot_id=row["id"],
        source_native_id=row["source_native_id"],
        language_code=row["language_code"],
        provider_set_id=row["provider_set_id"],
        provider_set_name=row["provider_set_name"],
        provider_card_name=row["provider_card_name"],
        local_id=row["local_id"],
        official_card_count=row["official_card_count"],
        variants=variants,
        observed_at=row["observed_at"],
    )


def lookup_tcgdex_macro(
    kb: KnowledgeBase,
    *,
    language_code: str,
    card_name: str,
    set_name: str,
    card_number: str,
) -> TCGdexMacroLookupResult:
    """Resolve only from each TCGdex native ID's latest immutable snapshot."""

    source_id = _source_id(kb)
    local_id, denominator = _split_card_number(card_number)
    lookup_key = macro_lookup_key(
        language_code=language_code,
        card_name=card_name,
        set_name=set_name,
        local_id=local_id,
    )
    rows: Sequence[Mapping[str, Any]] = kb.connection.execute(
        """
        WITH ranked AS (
            SELECT s.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY s.source_native_id, s.language_code
                       ORDER BY s.observed_at DESC, s.created_at DESC, s.id DESC
                   ) AS latest_rank
            FROM catalog_identity_snapshot AS s
            WHERE s.source_system_id = ? AND s.language_code = ?
        )
        SELECT * FROM ranked
        WHERE latest_rank = 1 AND macro_lookup_key_sha256 = ?
        ORDER BY source_native_id
        """,
        (source_id, _language(language_code), lookup_key),
    ).fetchall()
    candidates = tuple(_decode_candidate(row) for row in rows)
    if not candidates:
        return TCGdexMacroLookupResult(NO_MATCH)

    if denominator is not None:
        exact_denominator = tuple(
            candidate
            for candidate in candidates
            if candidate.official_card_count == denominator
        )
        denominator_unknown = tuple(
            candidate
            for candidate in candidates
            if candidate.official_card_count is None
        )
        if denominator_unknown:
            # Unknown denominator remains a possible competing identity.
            return TCGdexMacroLookupResult(
                DENOMINATOR_UNPROVEN,
                candidates=tuple(sorted(candidates, key=lambda c: c.source_native_id)),
            )
        if not exact_denominator:
            return TCGdexMacroLookupResult(
                DENOMINATOR_CONFLICT,
                candidates=tuple(sorted(candidates, key=lambda c: c.source_native_id)),
            )
        candidates = exact_denominator

    if len(candidates) != 1:
        return TCGdexMacroLookupResult(
            AMBIGUOUS,
            candidates=tuple(sorted(candidates, key=lambda c: c.source_native_id)),
        )
    return TCGdexMacroLookupResult(
        MATCHED,
        candidate=candidates[0],
        candidates=candidates,
    )
