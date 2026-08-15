"""Optional Robot KB/Neon cache for previously proven TCGdex macro identities.

The adapter is intentionally narrow:

* it reads/writes only the dedicated ``catalog_identity_snapshot`` table;
* it never creates a commercial microvariant or treats cached variant metadata
  as listing proof;
* it is consulted only by the emergency resolver after a genuine TCGdex
  technical outage;
* database/schema failures are non-fatal and fall through to the normal
  catalogue chain;
* the database URL is never rendered or persisted by this module.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

from .card_identity_catalog import CatalogIdentityResult, _language_code, _local_card_number, _normalize
from .models import CardIdentity
from .poketrace_matching import _card_number_parts
from .poketrace_set_bridge import OfficialSetName, TCGdexSetProvenance


ROBOT_KB_TCGDEX_CACHE = "ROBOT_KB_TCGDEX_CACHE"
CACHE_MATCHED = "MATCHED"
CACHE_AMBIGUOUS = "AMBIGUOUS"
CACHE_NO_MATCH = "NO_MATCH"
CACHE_UNAVAILABLE = "UNAVAILABLE"


def _truthy(value: object) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _macro_lookup_key(
    *, language_code: str, card_name: str, set_name: str, local_id: str
) -> str:
    payload = {
        "language_code": str(language_code or "").strip().casefold(),
        "card_name": _normalize(card_name),
        "set_name": _normalize(set_name),
        "local_id": _normalize(_local_card_number(local_id)),
    }
    if not all(payload.values()):
        return ""
    return _sha256(payload)


def _official_denominator(value: object) -> Optional[int]:
    _numerator, denominator = _card_number_parts(value)
    if denominator and str(denominator).isdigit() and int(str(denominator)) > 0:
        return int(str(denominator))
    return None


def _canonical_number(local_id: object, official_count: object) -> str:
    local = str(local_id or "").strip()
    if not local:
        return ""
    try:
        count = int(official_count) if official_count is not None else None
    except (TypeError, ValueError):
        count = None
    if count and count > 0:
        return f"{local}/{count}"
    return local


@dataclass
class RobotKBIdentityCacheCounters:
    lookup_attempts: int = 0
    lookup_hits: int = 0
    lookup_no_match: int = 0
    lookup_ambiguous: int = 0
    lookup_unavailable: int = 0
    write_attempts: int = 0
    write_inserted: int = 0
    write_idempotent: int = 0
    write_unavailable: int = 0
    schema_unavailable: int = 0
    connection_failures: int = 0
    disabled_skips: int = 0


@dataclass(frozen=True)
class RobotKBCacheResolution:
    identity: CardIdentity
    status: str = CACHE_NO_MATCH
    set_provenance: Optional[TCGdexSetProvenance] = None

    @property
    def matched(self) -> bool:
        return self.status == CACHE_MATCHED

    @property
    def ambiguous(self) -> bool:
        return self.status == CACHE_AMBIGUOUS


class RobotKBIdentityCache:
    """Small fail-safe PostgreSQL adapter for the Robot KB identity snapshot table."""

    def __init__(
        self,
        *,
        enabled: bool,
        database_url: Optional[str],
        connection_factory: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self.enabled = bool(enabled and database_url)
        self.database_url = database_url or None
        self.connection_factory = connection_factory
        self.counters = RobotKBIdentityCacheCounters()
        self._connection = None
        self._schema_checked = False
        self._schema_available = False
        self._circuit_open = False
        self._tcgdex_source_id: Optional[str] = None

    @classmethod
    def from_env(cls) -> "RobotKBIdentityCache":
        return cls(
            enabled=_truthy(os.getenv("V5_ROBOT_KB_IDENTITY_CACHE_ENABLED", "false")),
            database_url=os.getenv("ROBOT_KB_DATABASE_URL", "").strip() or None,
        )

    @staticmethod
    def _default_connection_factory(database_url: str):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(database_url, autocommit=True, row_factory=dict_row)

    def _connect(self):
        if not self.enabled or self._circuit_open or not self.database_url:
            return None
        if self._connection is not None:
            return self._connection
        factory = self.connection_factory or self._default_connection_factory
        try:
            self._connection = factory(self.database_url)
        except Exception:
            self.counters.connection_failures += 1
            self._circuit_open = True
            return None
        return self._connection

    def _prepare(self):
        connection = self._connect()
        if connection is None:
            return None
        if not self._schema_checked:
            self._schema_checked = True
            try:
                row = connection.execute(
                    "SELECT to_regclass('public.catalog_identity_snapshot') AS table_name"
                ).fetchone()
                self._schema_available = bool(row and row["table_name"])
            except Exception:
                self._schema_available = False
            if not self._schema_available:
                self.counters.schema_unavailable += 1
                return None
        if not self._schema_available:
            return None
        if self._tcgdex_source_id is None:
            try:
                row = connection.execute(
                    "SELECT id FROM source_system WHERE code = %s LIMIT 1",
                    ("tcgdex",),
                ).fetchone()
            except Exception:
                self.counters.connection_failures += 1
                self._circuit_open = True
                return None
            if row is None:
                self.counters.schema_unavailable += 1
                self._schema_available = False
                return None
            self._tcgdex_source_id = str(row["id"])
        return connection

    def lookup(self, identity: CardIdentity) -> RobotKBCacheResolution:
        if not self.enabled:
            self.counters.disabled_skips += 1
            return RobotKBCacheResolution(identity, CACHE_UNAVAILABLE)
        self.counters.lookup_attempts += 1

        language = _language_code(identity.language)
        local_id = _local_card_number(identity.card_number or "")
        if not (language and identity.card_name and identity.set and local_id):
            self.counters.lookup_no_match += 1
            return RobotKBCacheResolution(identity, CACHE_NO_MATCH)
        lookup_key = _macro_lookup_key(
            language_code=language,
            card_name=str(identity.card_name),
            set_name=str(identity.set),
            local_id=local_id,
        )
        if not lookup_key:
            self.counters.lookup_no_match += 1
            return RobotKBCacheResolution(identity, CACHE_NO_MATCH)

        connection = self._prepare()
        if connection is None:
            self.counters.lookup_unavailable += 1
            return RobotKBCacheResolution(identity, CACHE_UNAVAILABLE)

        try:
            rows: Sequence[Mapping[str, Any]] = connection.execute(
                """
                WITH ranked AS (
                    SELECT s.*,
                           ROW_NUMBER() OVER (
                               PARTITION BY s.source_native_id, s.language_code
                               ORDER BY s.observed_at DESC, s.created_at DESC, s.id DESC
                           ) AS latest_rank
                    FROM catalog_identity_snapshot AS s
                    WHERE s.source_system_id = %s AND s.language_code = %s
                )
                SELECT id, source_native_id, language_code, provider_set_id,
                       provider_set_name, provider_card_name, local_id,
                       official_card_count, observed_at
                FROM ranked
                WHERE latest_rank = 1 AND macro_lookup_key_sha256 = %s
                ORDER BY source_native_id
                """,
                (self._tcgdex_source_id, language, lookup_key),
            ).fetchall()
        except Exception:
            self.counters.connection_failures += 1
            self._circuit_open = True
            self.counters.lookup_unavailable += 1
            return RobotKBCacheResolution(identity, CACHE_UNAVAILABLE)

        if not rows:
            self.counters.lookup_no_match += 1
            return RobotKBCacheResolution(identity, CACHE_NO_MATCH)
        if len(rows) != 1:
            self.counters.lookup_ambiguous += 1
            return RobotKBCacheResolution(identity, CACHE_AMBIGUOUS)

        row = rows[0]
        listing_num, listing_den = _card_number_parts(identity.card_number)
        cached_num, _cached_den = _card_number_parts(row["local_id"])
        if not listing_num or listing_num != cached_num:
            self.counters.lookup_no_match += 1
            return RobotKBCacheResolution(identity, CACHE_NO_MATCH)
        official = row["official_card_count"]
        if listing_den is not None:
            if official is None or str(official) != str(listing_den):
                self.counters.lookup_no_match += 1
                return RobotKBCacheResolution(identity, CACHE_NO_MATCH)

        canonical_number = _canonical_number(row["local_id"], official)
        resolved = replace(
            identity,
            game=identity.game or "Pokémon TCG",
            card_name=str(row["provider_card_name"]),
            set=str(row["provider_set_name"]),
            card_number=canonical_number or identity.card_number,
        )
        provenance = TCGdexSetProvenance(
            listing_set=str(identity.set or "").strip(),
            listing_language=str(identity.language or language).strip(),
            language=str(row["language_code"]),
            set_id=str(row["provider_set_id"]),
            set_name=str(row["provider_set_name"]),
            official_names=(
                OfficialSetName(str(row["language_code"]), str(row["provider_set_name"])),
            ),
            catalog_card_id=str(row["source_native_id"]),
            catalog_card_name=str(row["provider_card_name"]),
            local_id=str(row["local_id"]),
        )
        self.counters.lookup_hits += 1
        return RobotKBCacheResolution(resolved, CACHE_MATCHED, provenance)

    def store_tcgdex_result(self, result: CatalogIdentityResult) -> None:
        if not self.enabled:
            self.counters.disabled_skips += 1
            return
        if not (
            result.matched
            and not result.ambiguous
            and not result.blocking
            and result.source == "TCGDEX"
            and result.set_provenance is not None
        ):
            return

        provenance = result.set_provenance
        language = str(provenance.language or "").strip().casefold()
        local_id = str(provenance.local_id or "").strip()
        if not (
            language
            and provenance.catalog_card_id
            and provenance.catalog_card_name
            and provenance.set_id
            and provenance.set_name
            and local_id
        ):
            return
        lookup_key = _macro_lookup_key(
            language_code=language,
            card_name=provenance.catalog_card_name,
            set_name=provenance.set_name,
            local_id=local_id,
        )
        if not lookup_key:
            return

        self.counters.write_attempts += 1
        connection = self._prepare()
        if connection is None:
            self.counters.write_unavailable += 1
            return

        official_count = _official_denominator(result.identity.card_number)
        fingerprint_payload = {
            "source_native_id": provenance.catalog_card_id,
            "language_code": language,
            "provider_set_id": provenance.set_id,
            "provider_set_name": provenance.set_name,
            "provider_card_name": provenance.catalog_card_name,
            "local_id": local_id,
            "official_card_count": official_count,
            "variants": None,
        }
        fingerprint = _sha256(fingerprint_payload)
        observed_at = _now()
        try:
            latest = connection.execute(
                """
                SELECT id, fingerprint_sha256
                FROM catalog_identity_snapshot
                WHERE source_system_id = %s AND source_native_id = %s
                  AND language_code = %s
                ORDER BY observed_at DESC, created_at DESC, id DESC
                LIMIT 1
                """,
                (self._tcgdex_source_id, provenance.catalog_card_id, language),
            ).fetchone()
            if latest is not None and latest["fingerprint_sha256"] == fingerprint:
                self.counters.write_idempotent += 1
                return

            snapshot_id = "catalog_" + _sha256(
                {
                    "source_system_id": self._tcgdex_source_id,
                    "source_native_id": provenance.catalog_card_id,
                    "language_code": language,
                    "fingerprint_sha256": fingerprint,
                    "observed_at": observed_at,
                }
            )[:24]
            connection.execute(
                """
                INSERT INTO catalog_identity_snapshot(
                    id, source_system_id, source_native_id, language_code,
                    provider_set_id, provider_set_name, provider_card_name, local_id,
                    official_card_count, variants_json, macro_lookup_key_sha256,
                    fingerprint_sha256, observed_at, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s, %s, %s, %s)
                """,
                (
                    snapshot_id,
                    self._tcgdex_source_id,
                    provenance.catalog_card_id,
                    language,
                    provenance.set_id,
                    provenance.set_name,
                    provenance.catalog_card_name,
                    local_id,
                    official_count,
                    lookup_key,
                    fingerprint,
                    observed_at,
                    observed_at,
                ),
            )
            self.counters.write_inserted += 1
        except Exception:
            self.counters.connection_failures += 1
            self._circuit_open = True
            self.counters.write_unavailable += 1

    def close(self) -> None:
        connection = self._connection
        self._connection = None
        if connection is None:
            return
        try:
            connection.close()
        except Exception:
            return


def render_robot_kb_identity_cache(cache: RobotKBIdentityCache) -> str:
    c = cache.counters
    return "\n".join(
        (
            "=== V5 ROBOT KB TCGDEX IDENTITY CACHE ===",
            f"enabled: {str(cache.enabled).lower()}",
            "consulted on clean TCGdex no-match: false",
            "cached microvariant metadata used as listing proof: false",
            f"lookup attempts: {c.lookup_attempts}",
            f"lookup hits: {c.lookup_hits}",
            f"lookup no-match: {c.lookup_no_match}",
            f"lookup ambiguous: {c.lookup_ambiguous}",
            f"lookup unavailable: {c.lookup_unavailable}",
            f"write attempts: {c.write_attempts}",
            f"write inserted: {c.write_inserted}",
            f"write idempotent: {c.write_idempotent}",
            f"write unavailable: {c.write_unavailable}",
            f"schema unavailable: {c.schema_unavailable}",
            f"connection failures: {c.connection_failures}",
        )
    )
