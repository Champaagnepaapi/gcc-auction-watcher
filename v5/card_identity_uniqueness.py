from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Optional, Tuple

from .card_identity_catalog import (
    TCGDEX_BASE,
    CatalogIdentityResult,
    HybridPokemonCardResolver,
    _card_number_parts,
    _canonical_value_changed,
    _language_code,
    _local_card_number_candidates,
    _normalize,
    _safe_year_from_release_date,
    _tcgdex_printed_card_number,
    _with_catalog_identity,
)
from .models import CardIdentity
from .microvariants import MICROVARIANT_APPLICABILITY_UNKNOWN
from .poketrace_set_bridge import OfficialSetName, TCGdexSetProvenance
from .variant_semantics import tcgdex_variant_supports_identity


# This is a safety cap, not a ranking threshold. If a catalogue query produces
# this many candidates before uniqueness can be proven, fail closed instead of
# inspecting only a truncated sample and accidentally declaring uniqueness.
TCGDEX_UNIQUENESS_MAX_CANDIDATES = 12


@dataclass
class CatalogUniquenessCounters:
    attempts: int = 0
    name_number_attempts: int = 0
    name_number_hits: int = 0
    name_number_no_match: int = 0
    name_number_ambiguous: int = 0
    set_name_attempts: int = 0
    set_name_hits: int = 0
    set_name_no_match: int = 0
    set_name_ambiguous: int = 0
    candidate_overflow: int = 0
    recovered_sets: int = 0
    recovered_numbers: int = 0
    variant_conflicts: int = 0


@dataclass(frozen=True)
class _ExactCatalogCard:
    card: Mapping[str, object]
    language: str


class DeterministicUniquenessHybridPokemonCardResolver(HybridPokemonCardResolver):
    """Add exact catalogue-cardinality rescue before the existing fallbacks.

    The normal V5 route remains exact set + card number. This resolver adds two
    conservative missing-coordinate routes:

    * exact card name + complete printed number -> recover set only when TCGdex
      contains exactly one compatible macro card in the listing language;
    * exact set + exact card name -> recover number only when that exact set
      contains exactly one card with that name.

    A single field is never enough. No fuzzy score, containment, substring or
    provider-market candidate is accepted as identity proof. Macro uniqueness
    also does not prove First Edition, Unlimited, holo/reverse or any other
    microvariant; the existing microvariant gates still run afterwards.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.uniqueness_counters = CatalogUniquenessCounters()
        self._uniqueness_set_payload_cache: dict[
            Tuple[str, str], Optional[Mapping[str, object]]
        ] = {}
        self._uniqueness_card_query_cache: dict[
            Tuple[str, str, str], Tuple[Mapping[str, object], ...]
        ] = {}

    @staticmethod
    def _complete_printed_number(value: object) -> Optional[Tuple[str, str]]:
        numerator, denominator = _card_number_parts(value)
        if not numerator or not denominator:
            return None
        return numerator, denominator

    @classmethod
    def _same_complete_printed_number(cls, left: object, right: object) -> bool:
        left_parts = cls._complete_printed_number(left)
        right_parts = cls._complete_printed_number(right)
        return bool(left_parts and right_parts and left_parts == right_parts)

    def resolve_identity(self, identity: CardIdentity) -> CatalogIdentityResult:
        # Preserve the exact set+number path byte-for-byte through the existing
        # Hybrid resolver. The uniqueness lane exists only for one missing core
        # coordinate and therefore cannot weaken an already-complete identity.
        if identity.set and identity.card_number:
            return super().resolve_identity(identity)

        key = self._identity_key(identity)
        cached = self._identity_cache.get(key)
        if cached is not None:
            self.counters.cache_hits += 1
            return cached

        uniqueness = CatalogIdentityResult(identity)
        if (
            not identity.set
            and identity.card_name
            and self._complete_printed_number(identity.card_number)
        ):
            uniqueness = self._resolve_unique_name_number(identity)
        elif identity.set and identity.card_name and not identity.card_number:
            uniqueness = self._resolve_unique_set_name(identity)

        if uniqueness.matched:
            self._register_exact_catalog_result(identity, uniqueness)
            self._identity_cache[key] = uniqueness
            return uniqueness
        if uniqueness.ambiguous or uniqueness.blocking:
            self._identity_cache[key] = uniqueness
            return uniqueness

        # Existing PokeTrace / Pokémon TCG fallbacks remain available after a
        # clean uniqueness no-match. They retain their pre-existing strict gates.
        return super().resolve_identity(identity)

    def resolve_microvariant_applicability(self, identity: CardIdentity):
        applicability = super().resolve_microvariant_applicability(identity)
        if applicability.status != MICROVARIANT_APPLICABILITY_UNKNOWN:
            return applicability
        # Language is a first-class identity discriminator. Do not use an
        # English/default catalogue retry to prove variant applicability for an
        # unknown or unsupported listing language.
        if not (
            _language_code(identity.language)
            and identity.card_name
            and self._complete_printed_number(identity.card_number)
        ):
            return applicability

        probe = replace(identity, set=None)
        exact = self._resolve_unique_name_number(probe)
        if not (exact.matched and not exact.ambiguous and not exact.blocking):
            return applicability
        if not self._post_macro_set_consistent(identity.set, exact):
            return applicability

        exact_applicability = exact.microvariant_applicability
        if exact_applicability.source != "TCGDEX_EXACT":
            return applicability

        original_key = self._identity_key(identity)
        self._microvariant_applicability_cache[original_key] = exact_applicability
        if exact_applicability.status != MICROVARIANT_APPLICABILITY_UNKNOWN:
            if self.counters.post_macro_applicability_unknown > 0:
                self.counters.post_macro_applicability_unknown -= 1
            self.counters.post_macro_applicability_resolved += 1
        return exact_applicability

    @staticmethod
    def _post_macro_set_consistent(
        listing_set: Optional[str],
        exact: CatalogIdentityResult,
    ) -> bool:
        if not listing_set or exact.set_provenance is None:
            return False
        provenance = exact.set_provenance
        exact_names = {
            _normalize(provenance.set_name),
            *(_normalize(value.name) for value in provenance.official_names),
        }
        exact_names.discard("")
        listing_normalized = _normalize(listing_set)
        if listing_normalized in exact_names:
            return True

        # Accept only an exact "CODE: Official Set Name" wrapper by comparing
        # the suffix byte-semantically after the same safe normalization.
        raw_listing = str(listing_set).strip()
        if ":" in raw_listing:
            suffix = _normalize(raw_listing.split(":", 1)[1])
            if suffix and suffix in exact_names:
                return True
        return False

    def _target_language(self, identity: CardIdentity) -> str:
        return _language_code(identity.language) or "en"

    def _query_name_number_briefs(
        self,
        language: str,
        card_name: str,
        card_number: str,
    ) -> Tuple[Mapping[str, object], ...]:
        candidates: dict[str, Mapping[str, object]] = {}
        for local_id in _local_card_number_candidates(card_number):
            cache_key = (language, _normalize(card_name), local_id.casefold())
            cached = self._uniqueness_card_query_cache.get(cache_key)
            if cached is None:
                payload = self._get_json(
                    f"{TCGDEX_BASE}/{language}/cards",
                    params={
                        # Retrieval may be case-insensitive/contains. Acceptance
                        # below is exact after safe Unicode/punctuation folding.
                        "name": card_name,
                        "localId": f"eq:{local_id}",
                        "pagination:page": "1",
                        "pagination:itemsPerPage": str(
                            TCGDEX_UNIQUENESS_MAX_CANDIDATES + 1
                        ),
                    },
                    provider="TCGDEX",
                    endpoint_kind="card_catalog",
                )
                rows = tuple(
                    item
                    for item in payload
                    if isinstance(item, Mapping)
                ) if isinstance(payload, list) else ()
                self._uniqueness_card_query_cache[cache_key] = rows
                cached = rows
            if len(cached) > TCGDEX_UNIQUENESS_MAX_CANDIDATES:
                self.uniqueness_counters.candidate_overflow += 1
                return cached
            for item in cached:
                if _normalize(item.get("name")) != _normalize(card_name):
                    continue
                brief_local = str(item.get("localId") or "").strip()
                brief_num, _brief_den = _card_number_parts(brief_local)
                wanted_num, _wanted_den = _card_number_parts(local_id)
                if not brief_num or brief_num != wanted_num:
                    continue
                card_id = str(item.get("id") or "").strip()
                if card_id:
                    candidates[card_id] = item
        return tuple(candidates.values())

    def _resolve_unique_name_number(
        self, identity: CardIdentity
    ) -> CatalogIdentityResult:
        self.uniqueness_counters.attempts += 1
        self.uniqueness_counters.name_number_attempts += 1
        language = self._target_language(identity)
        briefs = self._query_name_number_briefs(
            language,
            str(identity.card_name or "").strip(),
            str(identity.card_number or "").strip(),
        )
        if len(briefs) > TCGDEX_UNIQUENESS_MAX_CANDIDATES:
            self.uniqueness_counters.name_number_ambiguous += 1
            self.counters.ambiguous += 1
            return CatalogIdentityResult(identity, "TCGDEX", False, True)

        exact_cards: dict[Tuple[str, str, str], _ExactCatalogCard] = {}
        variant_conflict = False
        for brief in briefs:
            card_id = str(brief.get("id") or "").strip()
            if not card_id:
                continue
            card = self._tcgdex_card_by_exact_id(language, card_id)
            if not isinstance(card, Mapping):
                continue
            if _normalize(card.get("name")) != _normalize(identity.card_name):
                continue
            canonical_number = _tcgdex_printed_card_number(identity, card)
            if not self._same_complete_printed_number(
                identity.card_number, canonical_number
            ):
                continue
            set_payload = card.get("set")
            if not isinstance(set_payload, Mapping):
                continue
            set_id = str(set_payload.get("id") or "").strip()
            set_name = str(set_payload.get("name") or "").strip()
            local_id = str(card.get("localId") or "").strip()
            if not (set_id and set_name and local_id):
                continue
            release_year = _safe_year_from_release_date(set_payload.get("releaseDate"))
            if identity.year is not None and release_year is not None:
                if int(identity.year) != release_year:
                    continue
            supported = tcgdex_variant_supports_identity(identity, card)
            if supported is False:
                variant_conflict = True
                continue
            exact_cards[(card_id, set_id, local_id.casefold())] = _ExactCatalogCard(
                card, language
            )

        if len(exact_cards) > 1:
            self.uniqueness_counters.name_number_ambiguous += 1
            self.counters.ambiguous += 1
            return CatalogIdentityResult(identity, "TCGDEX", False, True)
        if not exact_cards:
            if variant_conflict:
                self.uniqueness_counters.variant_conflicts += 1
                self.uniqueness_counters.name_number_ambiguous += 1
                self.counters.ambiguous += 1
                return CatalogIdentityResult(identity, "TCGDEX", False, True)
            self.uniqueness_counters.name_number_no_match += 1
            return CatalogIdentityResult(identity)

        exact = next(iter(exact_cards.values()))
        result = self._catalog_result_from_card(identity, exact.card, exact.language)
        if not result.matched:
            self.uniqueness_counters.name_number_no_match += 1
            return result
        self.uniqueness_counters.name_number_hits += 1
        self.uniqueness_counters.recovered_sets += 1
        return result

    def _exact_set_ids(self, identity: CardIdentity) -> Tuple[str, ...]:
        normalized_set = _normalize(identity.set)
        target_language = self._target_language(identity)
        lookup_languages = tuple(dict.fromkeys((target_language, "en", "fr")))
        exact_ids = {
            set_id
            for language in lookup_languages
            for set_id, name in self._tcgdex_all_sets(language)
            if _normalize(name) == normalized_set or _normalize(set_id) == normalized_set
        }
        return tuple(sorted(exact_ids))

    def _set_payload(
        self, language: str, set_id: str
    ) -> Optional[Mapping[str, object]]:
        key = (language, set_id)
        if key in self._uniqueness_set_payload_cache:
            return self._uniqueness_set_payload_cache[key]
        payload = self._get_json(
            f"{TCGDEX_BASE}/{language}/sets/{set_id}",
            provider="TCGDEX",
            endpoint_kind="set_catalog",
        )
        result = payload if isinstance(payload, Mapping) else None
        self._uniqueness_set_payload_cache[key] = result
        return result

    def _resolve_unique_set_name(
        self, identity: CardIdentity
    ) -> CatalogIdentityResult:
        self.uniqueness_counters.attempts += 1
        self.uniqueness_counters.set_name_attempts += 1
        set_ids = self._exact_set_ids(identity)
        if len(set_ids) > 1:
            self.uniqueness_counters.set_name_ambiguous += 1
            self.counters.ambiguous += 1
            return CatalogIdentityResult(identity, "TCGDEX", False, True)
        if not set_ids:
            self.uniqueness_counters.set_name_no_match += 1
            return CatalogIdentityResult(identity)

        language = self._target_language(identity)
        set_id = set_ids[0]
        set_payload = self._set_payload(language, set_id)
        cards = set_payload.get("cards") if isinstance(set_payload, Mapping) else None
        if not isinstance(cards, list):
            self.uniqueness_counters.set_name_no_match += 1
            return CatalogIdentityResult(identity)

        matching = [
            item
            for item in cards
            if isinstance(item, Mapping)
            and _normalize(item.get("name")) == _normalize(identity.card_name)
        ]
        if len(matching) > 1:
            self.uniqueness_counters.set_name_ambiguous += 1
            self.counters.ambiguous += 1
            return CatalogIdentityResult(identity, "TCGDEX", False, True)
        if not matching:
            self.uniqueness_counters.set_name_no_match += 1
            return CatalogIdentityResult(identity)

        card_id = str(matching[0].get("id") or "").strip()
        card = self._tcgdex_card_by_exact_id(language, card_id) if card_id else None
        if not isinstance(card, Mapping):
            self.uniqueness_counters.set_name_no_match += 1
            return CatalogIdentityResult(identity)
        if _normalize(card.get("name")) != _normalize(identity.card_name):
            self.uniqueness_counters.set_name_no_match += 1
            return CatalogIdentityResult(identity)
        card_set = card.get("set")
        card_set_id = (
            str(card_set.get("id") or "").strip()
            if isinstance(card_set, Mapping)
            else ""
        )
        if card_set_id != set_id:
            self.uniqueness_counters.set_name_ambiguous += 1
            self.counters.ambiguous += 1
            return CatalogIdentityResult(identity, "TCGDEX", False, True, True)
        if tcgdex_variant_supports_identity(identity, card) is False:
            self.uniqueness_counters.variant_conflicts += 1
            self.uniqueness_counters.set_name_ambiguous += 1
            self.counters.ambiguous += 1
            return CatalogIdentityResult(identity, "TCGDEX", False, True)

        result = self._catalog_result_from_card(identity, card, language)
        if not result.matched:
            self.uniqueness_counters.set_name_no_match += 1
            return result
        self.uniqueness_counters.set_name_hits += 1
        self.uniqueness_counters.recovered_numbers += 1
        return result

    def _catalog_result_from_card(
        self,
        identity: CardIdentity,
        card: Mapping[str, object],
        language: str,
    ) -> CatalogIdentityResult:
        card_id = str(card.get("id") or "").strip()
        local_id = str(card.get("localId") or "").strip()
        card_name = str(card.get("name") or "").strip()
        set_payload = card.get("set")
        if not isinstance(set_payload, Mapping):
            return CatalogIdentityResult(identity)
        set_id = str(set_payload.get("id") or "").strip()
        set_name = str(set_payload.get("name") or "").strip()
        if not (card_id and local_id and card_name and set_id and set_name):
            return CatalogIdentityResult(identity)

        canonical_number = _tcgdex_printed_card_number(identity, card)
        if not canonical_number:
            return CatalogIdentityResult(identity)
        release_year = _safe_year_from_release_date(set_payload.get("releaseDate"))
        resolved = _with_catalog_identity(
            identity,
            card_name=card_name,
            set_name=set_name,
            card_number=canonical_number,
            year=release_year,
        )

        provider_alias = None
        if language != "en":
            provider_alias = self._exact_english_provider_alias(card, set_id=set_id)
        official_names = {OfficialSetName(language, set_name)}
        if provider_alias is not None:
            official_names.add(OfficialSetName("en", provider_alias.search_set_name))
        provenance = TCGdexSetProvenance(
            # For a recovered set there was no listing set. The exact recovered
            # localized TCGdex set is used as the provenance coordinate; this
            # does not rewrite the listing language or any microvariant field.
            listing_set=str(identity.set or set_name).strip(),
            listing_language=str(identity.language or language).strip(),
            language=language,
            set_id=set_id,
            set_name=set_name,
            official_names=tuple(
                sorted(official_names, key=lambda value: (value.language, value.name))
            ),
            catalog_card_id=card_id,
            catalog_card_name=card_name,
            local_id=local_id,
        )
        return CatalogIdentityResult(
            resolved,
            "TCGDEX",
            True,
            False,
            False,
            provider_alias,
            # Same exact card object feeds the existing applicability model.
            # Macro uniqueness itself is never edition/finish evidence.
            self.resolve_microvariant_applicability_from_card(card),
            provenance,
        )

    @staticmethod
    def resolve_microvariant_applicability_from_card(card: Mapping[str, object]):
        # Local import keeps this module's public surface narrowly focused.
        from .microvariants import tcgdex_microvariant_applicability

        return tcgdex_microvariant_applicability(card)

    def _register_exact_catalog_result(
        self,
        original: CardIdentity,
        result: CatalogIdentityResult,
    ) -> None:
        if result.set_provenance is not None:
            self.poketrace_identity.register_set_provenance(
                original, result.set_provenance
            )
            self.poketrace_identity.register_set_provenance(
                result.identity, result.set_provenance
            )
        if result.provider_alias is not None:
            self.poketrace_identity.register_provider_alias(
                result.identity, result.provider_alias
            )
            self.counters.alias_identity_calls_avoided_by_tcgdex_exact += 1

        self.counters.tcgdex_hits += 1
        self.counters.tcgdex_only_rescues += 1
        self.counters.tcgdex_poketrace_calls_avoided += 1
        self.counters.canonical_name_changes += int(
            _canonical_value_changed(original.card_name, result.identity.card_name)
        )
        self.counters.canonical_set_changes += int(
            _canonical_value_changed(original.set, result.identity.set)
        )
        self.counters.canonical_card_number_changes += int(
            _canonical_value_changed(original.card_number, result.identity.card_number)
        )


def render_catalog_uniqueness_counters(
    resolver: DeterministicUniquenessHybridPokemonCardResolver,
) -> str:
    c = resolver.uniqueness_counters
    return "\n".join(
        (
            "=== V5 DETERMINISTIC CATALOG UNIQUENESS ===",
            f"attempts: {c.attempts}",
            f"name+full-number attempts: {c.name_number_attempts}",
            f"name+full-number unique hits: {c.name_number_hits}",
            f"name+full-number no match: {c.name_number_no_match}",
            f"name+full-number ambiguous: {c.name_number_ambiguous}",
            f"exact-set+name attempts: {c.set_name_attempts}",
            f"exact-set+name unique hits: {c.set_name_hits}",
            f"exact-set+name no match: {c.set_name_no_match}",
            f"exact-set+name ambiguous: {c.set_name_ambiguous}",
            f"candidate overflow blocked: {c.candidate_overflow}",
            f"sets recovered: {c.recovered_sets}",
            f"numbers recovered: {c.recovered_numbers}",
            f"variant conflicts blocked: {c.variant_conflicts}",
            "single-coordinate resolution: 0",
            "fuzzy acceptance added: 0",
        )
    )
