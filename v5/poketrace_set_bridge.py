"""Deterministic TCGdex -> PokeTrace set nomenclature bridge.

The bridge never changes a listing identity.  It carries exact catalogue
provenance alongside that identity and may prove only the set component of an
already exact card-name + collector-number match.  There is intentionally no
substring, token-overlap, edit-distance or fuzzy-ratio path in this module.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence, Tuple

from .models import ProviderSearchAlias, TCGDEX_EXACT_ENGLISH_TWIN


SET_BRIDGE_EXACT = "SET_BRIDGE_EXACT"
SET_BRIDGE_NO_MAPPING = "SET_BRIDGE_NO_MAPPING"
SET_BRIDGE_AMBIGUOUS = "SET_BRIDGE_AMBIGUOUS"
SET_BRIDGE_COLLISION = "SET_BRIDGE_COLLISION"

BRIDGE_TCGDEX_ALIAS = "TCGDEX_OFFICIAL_ALIAS"
BRIDGE_ENGLISH_TWIN = "TCGDEX_EXACT_ENGLISH_TWIN"
BRIDGE_VERSIONED_MAPPING = "VERSIONED_EXACT_MAPPING"
BRIDGE_OBSERVED_EXACT = "POKETRACE_OBSERVED_EXACT_SET_KEY"

NO_BRIDGE_PROVENANCE = "NO_TCGDEX_EXACT_PROVENANCE"
NO_PROVIDER_SET_METADATA = "PROVIDER_SET_METADATA_MISSING"
NO_DETERMINISTIC_RELATION = "NO_DETERMINISTIC_SET_RELATION"
CORE_IDENTITY_NOT_EXACT = "NAME_OR_NUMBER_NOT_EXACT"
LANGUAGE_CONFLICT = "LANGUAGE_CONFLICT"
ALIAS_AMBIGUOUS = "OFFICIAL_ALIAS_MAPS_MULTIPLE_SETS"
PROVIDER_KEY_CONFLICT = "PROVIDER_SET_KEY_CONFLICT"
TCGDEX_PROVENANCE_CONFLICT = "TCGDEX_PROVENANCE_CONFLICT"


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


_LANGUAGE_KEYS = {
    "en": "en",
    "english": "en",
    "anglais": "en",
    "fr": "fr",
    "french": "fr",
    "francais": "fr",
    "de": "de",
    "german": "de",
    "deutsch": "de",
    "allemand": "de",
    "it": "it",
    "italian": "it",
    "italiano": "it",
    "italien": "it",
    "es": "es",
    "spanish": "es",
    "espanol": "es",
    "espagnol": "es",
    "ja": "ja",
    "jp": "ja",
    "japanese": "ja",
    "japonais": "ja",
}


def _language_key(value: object) -> str:
    normalized = _normalize(value)
    return _LANGUAGE_KEYS.get(normalized, normalized)


@dataclass(frozen=True)
class OfficialSetName:
    language: str
    name: str


@dataclass(frozen=True)
class TCGdexSetProvenance:
    """Exact TCGdex coordinates kept separately from the listing identity."""

    listing_set: str
    listing_language: str
    language: str
    set_id: str
    set_name: str
    official_names: Tuple[OfficialSetName, ...]
    catalog_card_id: str
    catalog_card_name: str
    local_id: str

    def valid(self) -> bool:
        return bool(
            self.listing_set.strip()
            and self.language.strip()
            and self.set_id.strip()
            and self.set_name.strip()
            and self.catalog_card_id.strip()
            and self.catalog_card_name.strip()
            and self.local_id.strip()
        )

    def cache_key(self) -> Tuple[str, ...]:
        return (
            _normalize(self.listing_set),
            _language_key(self.listing_language),
            _language_key(self.language),
            self.set_id.casefold(),
            _normalize(self.set_name),
            self.catalog_card_id,
            self.local_id.casefold(),
            *(
                f"{_language_key(value.language)}:{_normalize(value.name)}"
                for value in self.official_names
            ),
        )


@dataclass(frozen=True)
class VersionedPokeTraceSetMapping:
    """Small reviewed exception; production defaults to no manual mappings."""

    mapping_id: str
    version: str
    source: str
    tcgdex_set_id: str
    provider_names: Tuple[str, ...] = ()
    provider_slugs: Tuple[str, ...] = ()
    provider_set_ids: Tuple[str, ...] = ()

    def valid(self) -> bool:
        return bool(
            self.mapping_id.strip()
            and self.version.strip()
            and self.source.strip()
            and self.tcgdex_set_id.strip()
            and (
                self.provider_names
                or self.provider_slugs
                or self.provider_set_ids
            )
        )


# No broad/manual Pokemon-set table is shipped.  A future exception must be a
# reviewed VersionedPokeTraceSetMapping with source, version and offline tests.
VERSIONED_POKETRACE_SET_MAPPINGS: Tuple[VersionedPokeTraceSetMapping, ...] = ()


@dataclass(frozen=True)
class PokeTraceSetCollisionIndex:
    ambiguous_names: frozenset[str] = frozenset()
    ambiguous_slugs: frozenset[str] = frozenset()
    ambiguous_ids: frozenset[str] = frozenset()

    def conflicts(self, name: object, slug: object, set_id: object) -> bool:
        return bool(
            (_normalize(name) and _normalize(name) in self.ambiguous_names)
            or (_normalize(slug) and _normalize(slug) in self.ambiguous_slugs)
            or (_normalize(set_id) and _normalize(set_id) in self.ambiguous_ids)
        )


@dataclass(frozen=True)
class SetBridgeDecision:
    status: str
    reason: str
    listing_set: Optional[str] = None
    tcgdex_set_id: Optional[str] = None
    tcgdex_set_name: Optional[str] = None
    provider_set_name: Optional[str] = None
    provider_set_slug: Optional[str] = None
    provider_set_id: Optional[str] = None

    @property
    def exact(self) -> bool:
        return self.status == SET_BRIDGE_EXACT


@dataclass
class SetBridgeCounters:
    set_bridge_attempts: int = 0
    set_bridge_exact: int = 0
    set_bridge_no_mapping: int = 0
    set_bridge_ambiguous: int = 0
    set_bridge_collision: int = 0
    set_bridge_via_tcgdex_alias: int = 0
    set_bridge_via_english_twin: int = 0
    set_bridge_via_versioned_mapping: int = 0
    set_bridge_via_observed_exact: int = 0
    no_match_reasons: dict[str, int] = field(default_factory=dict)


def collision_index(
    candidates: Sequence[Mapping[str, object]],
) -> PokeTraceSetCollisionIndex:
    """Detect contradictory provider set keys within one response page."""

    name_ids: dict[str, set[str]] = {}
    slug_sets: dict[str, set[Tuple[str, str]]] = {}
    id_names: dict[str, set[str]] = {}
    for candidate in candidates:
        payload = candidate.get("set")
        if not isinstance(payload, Mapping):
            continue
        name = _normalize(payload.get("name"))
        slug = _normalize(payload.get("slug"))
        set_id = _normalize(payload.get("id"))
        if name and set_id:
            name_ids.setdefault(name, set()).add(set_id)
            id_names.setdefault(set_id, set()).add(name)
        if slug:
            slug_sets.setdefault(slug, set()).add((name, set_id))
    return PokeTraceSetCollisionIndex(
        ambiguous_names=frozenset(
            key for key, values in name_ids.items() if len(values) > 1
        ),
        ambiguous_slugs=frozenset(
            key for key, values in slug_sets.items() if len(values) > 1
        ),
        ambiguous_ids=frozenset(
            key for key, values in id_names.items() if len(values) > 1
        ),
    )


class DeterministicSetBridgeRegistry:
    """In-memory exact set bridge registry shared by identity and market paths."""

    def __init__(
        self,
        mappings: Sequence[
            VersionedPokeTraceSetMapping
        ] = VERSIONED_POKETRACE_SET_MAPPINGS,
    ) -> None:
        self.mappings = tuple(value for value in mappings if value.valid())
        self.counters = SetBridgeCounters()
        self._provenance: dict[Tuple[str, ...], TCGdexSetProvenance] = {}
        self._provenance_conflicts: set[Tuple[str, ...]] = set()
        self._official_alias_sets: dict[str, set[str]] = {}
        self._mapped_provider_keys: dict[Tuple[str, str], set[str]] = {}
        self._observed_provider_keys: dict[Tuple[str, str], set[str]] = {}
        self._observed_name_ids: dict[str, set[str]] = {}
        self._observed_slug_sets: dict[str, set[Tuple[str, str]]] = {}
        self._observed_id_names: dict[str, set[str]] = {}
        for mapping in self.mappings:
            for kind, values in (
                ("name", mapping.provider_names),
                ("slug", mapping.provider_slugs),
                ("id", mapping.provider_set_ids),
            ):
                for value in values:
                    normalized = _normalize(value)
                    if normalized:
                        self._mapped_provider_keys.setdefault(
                            (kind, normalized), set()
                        ).add(mapping.tcgdex_set_id)

    def register(
        self,
        identity_key: Tuple[str, ...],
        provenance: TCGdexSetProvenance,
    ) -> bool:
        if not provenance.valid():
            return False
        previous = self._provenance.get(identity_key)
        if previous is not None and previous != provenance:
            self._provenance_conflicts.add(identity_key)
            return False
        self._provenance[identity_key] = provenance
        aliases = {
            _normalize(provenance.listing_set),
            _normalize(provenance.set_name),
            *(_normalize(value.name) for value in provenance.official_names),
        }
        for alias in aliases:
            if alias:
                self._official_alias_sets.setdefault(alias, set()).add(
                    provenance.set_id
                )
        return True

    def provenance_for(
        self, identity_key: Tuple[str, ...]
    ) -> Optional[TCGdexSetProvenance]:
        return self._provenance.get(identity_key)

    def cache_key(self, identity_key: Tuple[str, ...]) -> Tuple[str, ...]:
        if identity_key in self._provenance_conflicts:
            return ("conflict",)
        provenance = self.provenance_for(identity_key)
        return provenance.cache_key() if provenance is not None else ("none",)

    def evaluate(
        self,
        identity_key: Tuple[str, ...],
        candidate: Mapping[str, object],
        *,
        provider_alias: Optional[ProviderSearchAlias],
        core_identity_exact: bool,
        collisions: PokeTraceSetCollisionIndex = PokeTraceSetCollisionIndex(),
    ) -> SetBridgeDecision:
        self.counters.set_bridge_attempts += 1
        provenance = self.provenance_for(identity_key)
        if provenance is None:
            return self._no_mapping(NO_BRIDGE_PROVENANCE)
        if identity_key in self._provenance_conflicts:
            return self._collision(
                TCGDEX_PROVENANCE_CONFLICT,
                provenance,
                "",
                "",
                "",
            )
        if not core_identity_exact:
            return self._no_mapping(CORE_IDENTITY_NOT_EXACT, provenance)

        set_payload = candidate.get("set")
        if not isinstance(set_payload, Mapping):
            return self._no_mapping(NO_PROVIDER_SET_METADATA, provenance)
        raw_name = str(set_payload.get("name") or "").strip()
        raw_slug = str(set_payload.get("slug") or "").strip()
        raw_id = str(set_payload.get("id") or "").strip()
        name, slug, set_id = map(_normalize, (raw_name, raw_slug, raw_id))
        if not (name or slug or set_id):
            return self._no_mapping(NO_PROVIDER_SET_METADATA, provenance)
        if collisions.conflicts(name, slug, set_id):
            return self._collision(PROVIDER_KEY_CONFLICT, provenance, raw_name, raw_slug, raw_id)
        if (
            (name and set_id and self._observed_name_ids.get(name, {set_id}) != {set_id})
            or (
                set_id
                and name
                and self._observed_id_names.get(set_id, {name}) != {name}
            )
            or (
                slug
                and (name or set_id)
                and self._observed_slug_sets.get(slug, {(name, set_id)})
                != {(name, set_id)}
            )
        ):
            return self._collision(
                PROVIDER_KEY_CONFLICT,
                provenance,
                raw_name,
                raw_slug,
                raw_id,
            )

        candidate_language = _language_key(
            candidate.get("language") or candidate.get("locale")
        )
        allowed_languages = {
            _language_key(provenance.language),
            _language_key(provenance.listing_language),
        }
        exact_twin = self._valid_english_twin(provenance, provider_alias)
        if exact_twin:
            allowed_languages.add("en")
        if candidate_language and candidate_language not in allowed_languages:
            return self._ambiguous(
                LANGUAGE_CONFLICT, provenance, raw_name, raw_slug, raw_id
            )

        target = provenance.set_id
        provider_keys = tuple(
            (kind, value)
            for kind, value in (("name", name), ("slug", slug), ("id", set_id))
            if value
        )
        for key in provider_keys:
            known_sets = (
                self._mapped_provider_keys.get(key, set())
                | self._observed_provider_keys.get(key, set())
            )
            if known_sets and (target not in known_sets or len(known_sets) > 1):
                return self._collision(
                    PROVIDER_KEY_CONFLICT,
                    provenance,
                    raw_name,
                    raw_slug,
                    raw_id,
                )

        official_aliases = {
            _normalize(provenance.listing_set),
            _normalize(provenance.set_name),
            *(_normalize(value.name) for value in provenance.official_names),
        }
        # Provider slugs/IDs are separate namespaces. Only an exact provider
        # set.name may be compared to an official TCGdex name; slug/ID require
        # an observed exact key or a reviewed versioned mapping.
        official_matches = {name} if name and name in official_aliases else set()
        for value in official_matches:
            if len(self._official_alias_sets.get(value, {target})) > 1:
                return self._ambiguous(
                    ALIAS_AMBIGUOUS, provenance, raw_name, raw_slug, raw_id
                )

        source = None
        if exact_twin:
            twin_set = _normalize(provider_alias.search_set_name)
            if twin_set and twin_set == name:
                source = BRIDGE_ENGLISH_TWIN
        if source is None and official_matches:
            source = BRIDGE_TCGDEX_ALIAS
        if source is None:
            for mapping in self.mappings:
                if mapping.tcgdex_set_id != target:
                    continue
                if any(
                    value
                    and value
                    in {
                        *(_normalize(item) for item in mapping.provider_names),
                        *(_normalize(item) for item in mapping.provider_slugs),
                        *(_normalize(item) for item in mapping.provider_set_ids),
                    }
                    for value in (name, slug, set_id)
                ):
                    source = BRIDGE_VERSIONED_MAPPING
                    break
        if source is None and any(
            self._observed_provider_keys.get(key) == {target}
            for key in provider_keys
        ):
            source = BRIDGE_OBSERVED_EXACT
        if source is None:
            return self._no_mapping(NO_DETERMINISTIC_RELATION, provenance)

        for key in provider_keys:
            self._observed_provider_keys.setdefault(key, set()).add(target)
        if name and set_id:
            self._observed_name_ids.setdefault(name, set()).add(set_id)
            self._observed_id_names.setdefault(set_id, set()).add(name)
        if slug and (name or set_id):
            self._observed_slug_sets.setdefault(slug, set()).add((name, set_id))
        self.counters.set_bridge_exact += 1
        if source == BRIDGE_TCGDEX_ALIAS:
            self.counters.set_bridge_via_tcgdex_alias += 1
        elif source == BRIDGE_ENGLISH_TWIN:
            self.counters.set_bridge_via_english_twin += 1
        elif source == BRIDGE_VERSIONED_MAPPING:
            self.counters.set_bridge_via_versioned_mapping += 1
        elif source == BRIDGE_OBSERVED_EXACT:
            self.counters.set_bridge_via_observed_exact += 1
        return SetBridgeDecision(
            SET_BRIDGE_EXACT,
            source,
            provenance.listing_set,
            provenance.set_id,
            provenance.set_name,
            raw_name or None,
            raw_slug or None,
            raw_id or None,
        )

    @staticmethod
    def _valid_english_twin(
        provenance: TCGdexSetProvenance,
        alias: Optional[ProviderSearchAlias],
    ) -> bool:
        return bool(
            alias is not None
            and alias.provenance == TCGDEX_EXACT_ENGLISH_TWIN
            and alias.catalog_card_id == provenance.catalog_card_id
            and alias.catalog_set_id == provenance.set_id
            and alias.catalog_local_id.casefold() == provenance.local_id.casefold()
        )

    def _no_mapping(
        self,
        reason: str,
        provenance: Optional[TCGdexSetProvenance] = None,
    ) -> SetBridgeDecision:
        self.counters.set_bridge_no_mapping += 1
        self.counters.no_match_reasons[reason] = (
            self.counters.no_match_reasons.get(reason, 0) + 1
        )
        return SetBridgeDecision(
            SET_BRIDGE_NO_MAPPING,
            reason,
            provenance.listing_set if provenance else None,
            provenance.set_id if provenance else None,
            provenance.set_name if provenance else None,
        )

    def _ambiguous(
        self,
        reason: str,
        provenance: TCGdexSetProvenance,
        name: str,
        slug: str,
        set_id: str,
    ) -> SetBridgeDecision:
        self.counters.set_bridge_ambiguous += 1
        return SetBridgeDecision(
            SET_BRIDGE_AMBIGUOUS,
            reason,
            provenance.listing_set,
            provenance.set_id,
            provenance.set_name,
            name or None,
            slug or None,
            set_id or None,
        )

    def _collision(
        self,
        reason: str,
        provenance: TCGdexSetProvenance,
        name: str,
        slug: str,
        set_id: str,
    ) -> SetBridgeDecision:
        self.counters.set_bridge_collision += 1
        return SetBridgeDecision(
            SET_BRIDGE_COLLISION,
            reason,
            provenance.listing_set,
            provenance.set_id,
            provenance.set_name,
            name or None,
            slug or None,
            set_id or None,
        )
