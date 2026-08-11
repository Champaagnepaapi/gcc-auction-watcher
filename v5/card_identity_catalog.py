from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Mapping, Optional, Tuple

import requests

from .ebay import CardNameLookupResult, SetNumberCardNameResolver
from .models import CardIdentity
from .poketrace_identity import PokeTraceIdentityResolver
from .poketrace_matching import _card_number_parts
from .variant_semantics import tcgdex_variant_supports_identity


TCGDEX_BASE = "https://api.tcgdex.net/v2"
POKEMON_TCG_BASE = "https://api.pokemontcg.io/v2"


# Only languages currently exposed by the TCGdex API are used as direct
# endpoints. Unsupported/ambiguous languages fall back to English catalogue
# metadata while the original CardIdentity.language remains untouched.
_LANGUAGE_CODES = {
    "english": "en",
    "anglais": "en",
    "en": "en",
    "french": "fr",
    "francais": "fr",
    "français": "fr",
    "fr": "fr",
    "german": "de",
    "allemand": "de",
    "de": "de",
    "spanish": "es",
    "espagnol": "es",
    "es": "es",
    "italian": "it",
    "italien": "it",
    "it": "it",
    "japanese": "ja",
    "japonais": "ja",
    "ja": "ja",
    "jp": "ja",
    "portuguese": "pt-br",
    "portugais": "pt-br",
    "brazilian portuguese": "pt-br",
    "pt": "pt-br",
    "pt br": "pt-br",
    "traditional chinese": "zh-tw",
    "chinese traditional": "zh-tw",
    "zh tw": "zh-tw",
    "indonesian": "id",
    "indonesien": "id",
    "id": "id",
    "thai": "th",
    "th": "th",
}


@dataclass
class CardCatalogCounters:
    tcgdex_requests: int = 0
    tcgdex_hits: int = 0
    pokemon_tcg_requests: int = 0
    pokemon_tcg_hits: int = 0
    ambiguous: int = 0
    no_match: int = 0
    failures: int = 0
    cache_hits: int = 0
    canonical_name_changes: int = 0
    canonical_set_changes: int = 0
    canonical_card_number_changes: int = 0
    tcgdex_numerator_only_canonicalizations: int = 0
    tcgdex_denominator_conflicts: int = 0
    tcgdex_set_alias_unique_resolutions: int = 0
    tcgdex_ambiguous_set_aliases: int = 0
    tcgdex_only_rescues: int = 0
    tcgdex_poketrace_calls_avoided: int = 0
    tcgdex_skipped_missing_fields: int = 0
    tcgdex_no_match_set: int = 0
    tcgdex_no_match_card: int = 0
    tcgdex_no_match_number_conflict: int = 0
    tcgdex_no_match_missing_name: int = 0
    tcgdex_no_match_set_conflict: int = 0
    tcgdex_transport_failures: int = 0
    tcgdex_http_failures: int = 0
    tcgdex_json_failures: int = 0
    tcgdex_set_catalog_failures: int = 0
    tcgdex_card_lookup_failures: int = 0
    tcgdex_local_id_alternates_tried: int = 0
    tcgdex_local_id_alternate_hits: int = 0
    tcgdex_direct_card_fallbacks: int = 0
    tcgdex_direct_card_hits: int = 0
    tcgdex_variant_impossible: int = 0
    tcgdex_unsupported_language_fallbacks: int = 0


@dataclass(frozen=True)
class CatalogIdentityResult:
    identity: CardIdentity
    source: str = "NONE"
    matched: bool = False
    ambiguous: bool = False
    blocking: bool = False


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _language_code(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return _LANGUAGE_CODES.get(_normalize(value))


def _local_card_number(value: str) -> str:
    compact = re.sub(r"\s+", "", value or "")
    return compact.split("/", 1)[0].lstrip("#")


def _local_card_number_candidates(value: str) -> Tuple[str, ...]:
    """Return only deterministic spelling alternatives for a TCGdex localId."""

    local = _local_card_number(value)
    if not local:
        return ()
    candidates = [local]
    if re.fullmatch(r"0*\d+", local):
        candidates.append(str(int(local)))
    elif re.fullmatch(r"[A-Za-z]+\d+[A-Za-z]*", local):
        candidates.append(local.upper())
    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))


def _safe_year_from_release_date(value: object) -> Optional[int]:
    match = re.match(r"\s*((?:19|20)\d{2})", str(value or ""))
    return int(match.group(1)) if match else None


def _with_catalog_identity(
    original: CardIdentity,
    *,
    card_name: Optional[str],
    set_name: Optional[str],
    card_number: Optional[str],
    year: Optional[int],
) -> CardIdentity:
    return replace(
        original,
        game=original.game or "Pokémon TCG",
        card_name=(card_name or original.card_name),
        set=(set_name or original.set),
        card_number=(card_number or original.card_number),
        year=(original.year if original.year is not None else year),
    )


def _numeric_tokens(value: object) -> frozenset[str]:
    return frozenset(re.findall(r"\d+(?:\.\d+)?", _normalize(value)))


def _set_name_similarity(expected: object, candidate: object) -> float:
    expected_norm = _normalize(expected)
    candidate_norm = _normalize(candidate)
    if not expected_norm or not candidate_norm:
        return 0.0
    if expected_norm == candidate_norm:
        return 1.0

    expected_numbers = _numeric_tokens(expected)
    candidate_numbers = _numeric_tokens(candidate)
    if expected_numbers != candidate_numbers and (expected_numbers or candidate_numbers):
        return 0.0

    expected_tokens = set(expected_norm.split())
    candidate_tokens = set(candidate_norm.split())
    intersection = len(expected_tokens & candidate_tokens)
    union = len(expected_tokens | candidate_tokens)
    jaccard = intersection / union if union else 0.0
    shorter, longer = sorted((expected_tokens, candidate_tokens), key=len)
    if shorter and shorter.issubset(longer) and intersection:
        return max(jaccard, 0.86)
    return jaccard


def _tcgdex_printed_card_number(
    original: CardIdentity, card: Mapping[str, object]
) -> Optional[str]:
    local_id = str(card.get("localId") or "").strip()
    if not local_id:
        return original.card_number
    if "/" in local_id:
        return local_id

    set_payload = card.get("set")
    card_count = (
        set_payload.get("cardCount")
        if isinstance(set_payload, Mapping)
        else None
    )
    official = (
        card_count.get("official")
        if isinstance(card_count, Mapping)
        else None
    )
    official_text = str(official or "").strip()
    if re.fullmatch(r"0*\d+", local_id) and re.fullmatch(r"[1-9]\d*", official_text):
        return f"{local_id}/{official_text}"

    original_number = str(original.card_number or "").strip()
    original_numerator, _original_denominator = _card_number_parts(original_number)
    local_numerator, _local_denominator = _card_number_parts(local_id)
    if original_number and original_numerator == local_numerator:
        return original_number
    return local_id


def _complete_card_number_conflict(original: object, canonical: object) -> bool:
    original_numerator, original_denominator = _card_number_parts(original)
    canonical_numerator, canonical_denominator = _card_number_parts(canonical)
    return bool(
        original_denominator
        and canonical_denominator
        and (
            original_numerator != canonical_numerator
            or original_denominator != canonical_denominator
        )
    )


def _canonical_value_changed(before: object, after: object) -> bool:
    return str(before or "").strip() != str(after or "").strip()


class MultilingualPokemonCardResolver(SetNumberCardNameResolver):
    """Resolve eBay identity through TCGdex, then Pokémon TCG API.

    TCGdex remains the multilingual primary catalogue. Set catalogues are loaded
    once per language/run and matched locally. Card lookup then uses only
    deterministic localId spelling alternatives and the two official TCGdex
    lookup shapes (set/localId and direct card id), with the returned card
    revalidated before acceptance.
    """

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        timeout_seconds: float = 12.0,
        pokemon_tcg_api_key: Optional[str] = None,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds
        self.pokemon_tcg_api_key = (
            pokemon_tcg_api_key
            if pokemon_tcg_api_key is not None
            else os.getenv("POKEMON_TCG_API_KEY", "").strip() or None
        )
        self.counters = CardCatalogCounters()
        self._identity_cache: dict[Tuple[str, ...], CatalogIdentityResult] = {}
        self._set_cache: dict[Tuple[str, str], Tuple[Tuple[str, str], ...]] = {}
        self._all_sets_cache: dict[str, Tuple[Tuple[str, str], ...]] = {}
        self._card_cache: dict[Tuple[str, str, str, str], Optional[Mapping[str, object]]] = {}

    @staticmethod
    def _identity_key(identity: CardIdentity) -> Tuple[str, ...]:
        return (
            _normalize(identity.set),
            _normalize(identity.card_number),
            _normalize(identity.language),
            _normalize(identity.card_name),
            str(identity.year or ""),
            _normalize(identity.variant),
        )

    def resolve(
        self,
        set_name: str,
        card_number: str,
        language: Optional[str],
        year: Optional[int],
        variant: Optional[str],
    ) -> CardNameLookupResult:
        result = self.resolve_identity(
            CardIdentity(
                game="Pokémon TCG",
                set=set_name,
                card_number=card_number,
                language=language,
                year=year,
                variant=variant,
            )
        )
        return CardNameLookupResult(
            result.identity.card_name if result.matched else None,
            result.ambiguous,
        )

    def resolve_identity(self, identity: CardIdentity) -> CatalogIdentityResult:
        if not identity.set or not identity.card_number:
            self.counters.tcgdex_skipped_missing_fields += 1
            return CatalogIdentityResult(identity)
        key = self._identity_key(identity)
        cached = self._identity_cache.get(key)
        if cached is not None:
            self.counters.cache_hits += 1
            return cached

        tcgdex = self._resolve_tcgdex(identity)
        if tcgdex.matched or tcgdex.ambiguous:
            self._identity_cache[key] = tcgdex
            return tcgdex

        fallback = self._resolve_pokemon_tcg(identity)
        if fallback.matched or fallback.ambiguous:
            self._identity_cache[key] = fallback
            return fallback

        result = CatalogIdentityResult(identity)
        self.counters.no_match += 1
        self._identity_cache[key] = result
        return result

    def _get_json(
        self,
        url: str,
        *,
        params: Optional[Mapping[str, str]] = None,
        headers: Optional[Mapping[str, str]] = None,
        provider: str,
        endpoint_kind: str = "other",
    ) -> object:
        if provider == "TCGDEX":
            self.counters.tcgdex_requests += 1
        else:
            self.counters.pokemon_tcg_requests += 1
        try:
            response = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException:
            self.counters.failures += 1
            if provider == "TCGDEX":
                self.counters.tcgdex_transport_failures += 1
                self._count_tcgdex_endpoint_failure(endpoint_kind)
            return None
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            self.counters.failures += 1
            if provider == "TCGDEX":
                self.counters.tcgdex_http_failures += 1
                self._count_tcgdex_endpoint_failure(endpoint_kind)
            return None
        try:
            return response.json()
        except ValueError:
            self.counters.failures += 1
            if provider == "TCGDEX":
                self.counters.tcgdex_json_failures += 1
                self._count_tcgdex_endpoint_failure(endpoint_kind)
            return None

    def _count_tcgdex_endpoint_failure(self, endpoint_kind: str) -> None:
        if endpoint_kind == "set_catalog":
            self.counters.tcgdex_set_catalog_failures += 1
        elif endpoint_kind in {"set_card", "direct_card"}:
            self.counters.tcgdex_card_lookup_failures += 1

    def _tcgdex_all_sets(self, language: str) -> Tuple[Tuple[str, str], ...]:
        cached = self._all_sets_cache.get(language)
        if cached is not None:
            return cached
        payload = self._get_json(
            f"{TCGDEX_BASE}/{language}/sets",
            provider="TCGDEX",
            endpoint_kind="set_catalog",
        )
        rows: list[Tuple[str, str]] = []
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, Mapping):
                    continue
                set_id = str(item.get("id") or "").strip()
                name = str(item.get("name") or "").strip()
                if set_id and name:
                    rows.append((set_id, name))
        result = tuple(dict.fromkeys(rows))
        self._all_sets_cache[language] = result
        return result

    def _tcgdex_sets(self, language: str, set_name: str) -> Tuple[Tuple[str, str], ...]:
        cache_key = (language, _normalize(set_name))
        cached = self._set_cache.get(cache_key)
        if cached is not None:
            return cached

        rows = self._tcgdex_all_sets(language)
        normalized_query = _normalize(set_name)
        exact = tuple(
            (set_id, name)
            for set_id, name in rows
            if _normalize(name) == normalized_query
            or _normalize(set_id) == normalized_query
        )
        if exact:
            self._set_cache[cache_key] = exact
            return exact

        scored = [
            (
                max(
                    _set_name_similarity(set_name, name),
                    _set_name_similarity(set_name, set_id),
                ),
                set_id,
                name,
            )
            for set_id, name in rows
        ]
        scored = [value for value in scored if value[0] >= 0.66]
        if not scored:
            result: Tuple[Tuple[str, str], ...] = ()
        else:
            best_score = max(score for score, _set_id, _name in scored)
            result = tuple(
                (set_id, name)
                for score, set_id, name in scored
                if score == best_score
            )
        self._set_cache[cache_key] = result
        return result

    def _tcgdex_card_route(
        self,
        language: str,
        set_id: str,
        local_number: str,
        *,
        route: str,
    ) -> Optional[Mapping[str, object]]:
        cache_key = (language, set_id, local_number, route)
        if cache_key in self._card_cache:
            return self._card_cache[cache_key]
        if route == "set_card":
            url = f"{TCGDEX_BASE}/{language}/sets/{set_id}/{local_number}"
        else:
            url = f"{TCGDEX_BASE}/{language}/cards/{set_id}-{local_number}"
        payload = self._get_json(
            url,
            provider="TCGDEX",
            endpoint_kind=route,
        )
        card = payload if isinstance(payload, Mapping) else None
        self._card_cache[cache_key] = card
        return card

    def _find_tcgdex_card(
        self, language: str, set_id: str, card_number: str
    ) -> Optional[Mapping[str, object]]:
        candidates = _local_card_number_candidates(card_number)
        for index, local_number in enumerate(candidates):
            if index:
                self.counters.tcgdex_local_id_alternates_tried += 1
            card = self._tcgdex_card_route(
                language, set_id, local_number, route="set_card"
            )
            if card is not None:
                if index:
                    self.counters.tcgdex_local_id_alternate_hits += 1
                return card

            self.counters.tcgdex_direct_card_fallbacks += 1
            card = self._tcgdex_card_route(
                language, set_id, local_number, route="direct_card"
            )
            if card is not None:
                self.counters.tcgdex_direct_card_hits += 1
                if index:
                    self.counters.tcgdex_local_id_alternate_hits += 1
                return card
        return None

    def _resolve_tcgdex(self, identity: CardIdentity) -> CatalogIdentityResult:
        normalized_language = _normalize(identity.language)
        language_code = _language_code(identity.language)
        target_language = language_code or "en"
        if identity.language and language_code is None:
            self.counters.tcgdex_unsupported_language_fallbacks += 1
        lookup_languages = tuple(dict.fromkeys((target_language, "en", "fr")))
        normalized_set = _normalize(identity.set)
        exact_ids: dict[str, str] = {}
        loose_ids: dict[str, str] = {}

        for language in lookup_languages:
            for set_id, name in self._tcgdex_sets(language, identity.set or ""):
                loose_ids.setdefault(set_id, name)
                if (
                    _normalize(name) == normalized_set
                    or _normalize(set_id) == normalized_set
                ):
                    exact_ids.setdefault(set_id, name)

        candidate_ids = exact_ids or loose_ids
        if len(candidate_ids) != 1:
            if len(candidate_ids) > 1:
                self.counters.ambiguous += 1
                self.counters.tcgdex_ambiguous_set_aliases += 1
                return CatalogIdentityResult(identity, "TCGDEX", False, True)
            self.counters.tcgdex_no_match_set += 1
            return CatalogIdentityResult(identity)

        set_id = next(iter(candidate_ids))
        candidate_set_name = candidate_ids[set_id]
        if (
            _normalize(candidate_set_name) != normalized_set
            or _normalize(set_id) == normalized_set
        ):
            self.counters.tcgdex_set_alias_unique_resolutions += 1
        local_candidates = _local_card_number_candidates(identity.card_number or "")
        if not local_candidates:
            self.counters.tcgdex_skipped_missing_fields += 1
            return CatalogIdentityResult(identity)

        card = self._find_tcgdex_card(target_language, set_id, identity.card_number or "")
        if card is None and target_language != "en":
            card = self._find_tcgdex_card("en", set_id, identity.card_number or "")
        if card is None:
            self.counters.tcgdex_no_match_card += 1
            return CatalogIdentityResult(identity)

        card_name = str(card.get("name") or "").strip() or None
        card_local_id = str(card.get("localId") or "").strip()
        card_local_numerator, _ = _card_number_parts(card_local_id)
        lookup_numerator, _ = _card_number_parts(local_candidates[0])
        if card_local_id and card_local_numerator != lookup_numerator:
            self.counters.ambiguous += 1
            self.counters.tcgdex_no_match_number_conflict += 1
            return CatalogIdentityResult(identity, "TCGDEX", False, True)

        set_payload = card.get("set")
        card_set_name = None
        release_year = None
        if isinstance(set_payload, Mapping):
            card_set_id = str(set_payload.get("id") or "").strip()
            if card_set_id and card_set_id != set_id:
                self.counters.ambiguous += 1
                self.counters.tcgdex_no_match_set_conflict += 1
                return CatalogIdentityResult(
                    identity, "TCGDEX", False, True, True
                )
            card_set_name = str(set_payload.get("name") or "").strip() or None
            release_year = _safe_year_from_release_date(set_payload.get("releaseDate"))
        if card_set_name is None:
            card_set_name = candidate_ids.get(set_id)

        if not card_name:
            self.counters.tcgdex_no_match_missing_name += 1
            return CatalogIdentityResult(identity)
        canonical_card_number = _tcgdex_printed_card_number(identity, card)
        if _complete_card_number_conflict(
            identity.card_number, canonical_card_number
        ):
            self.counters.ambiguous += 1
            self.counters.tcgdex_denominator_conflicts += 1
            self.counters.tcgdex_no_match_number_conflict += 1
            return CatalogIdentityResult(identity, "TCGDEX", False, True, True)

        variant_supported = tcgdex_variant_supports_identity(identity, card)
        if variant_supported is False:
            # TCGdex variants are availability metadata. An explicit False is
            # useful contradictory evidence, but PokeTrace may still resolve a
            # catalogue-data issue; therefore this is ambiguous, not blocking.
            self.counters.ambiguous += 1
            self.counters.tcgdex_variant_impossible += 1
            return CatalogIdentityResult(identity, "TCGDEX", False, True, False)

        resolved = _with_catalog_identity(
            identity,
            card_name=card_name,
            set_name=card_set_name,
            card_number=canonical_card_number,
            year=release_year,
        )
        original_numerator, original_denominator = _card_number_parts(
            identity.card_number
        )
        canonical_numerator, canonical_denominator = _card_number_parts(
            resolved.card_number
        )
        self.counters.tcgdex_numerator_only_canonicalizations += int(
            bool(
                original_numerator
                and original_denominator is None
                and canonical_denominator
                and original_numerator == canonical_numerator
            )
        )
        self.counters.canonical_name_changes += int(
            _canonical_value_changed(identity.card_name, resolved.card_name)
        )
        self.counters.canonical_set_changes += int(
            _canonical_value_changed(identity.set, resolved.set)
        )
        self.counters.canonical_card_number_changes += int(
            _canonical_value_changed(identity.card_number, resolved.card_number)
        )
        self.counters.tcgdex_hits += 1
        return CatalogIdentityResult(resolved, "TCGDEX", True, False)

    @staticmethod
    def _pokemon_query_escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _resolve_pokemon_tcg(self, identity: CardIdentity) -> CatalogIdentityResult:
        language = _language_code(identity.language)
        if language not in {None, "en"}:
            return CatalogIdentityResult(identity)
        local_number = _local_card_number(identity.card_number or "")
        if not local_number:
            return CatalogIdentityResult(identity)

        terms = [
            f'number:"{self._pokemon_query_escape(local_number)}"',
            f'set.name:"{self._pokemon_query_escape(identity.set or "")}"',
        ]
        if identity.card_name:
            terms.append(f'name:"{self._pokemon_query_escape(identity.card_name)}"')
        headers = {"Accept": "application/json"}
        if self.pokemon_tcg_api_key:
            headers["X-Api-Key"] = self.pokemon_tcg_api_key
        payload = self._get_json(
            f"{POKEMON_TCG_BASE}/cards",
            params={
                "q": " ".join(terms),
                "pageSize": "20",
                "select": "id,name,number,set",
            },
            headers=headers,
            provider="POKEMON_TCG",
        )
        if not isinstance(payload, Mapping):
            return CatalogIdentityResult(identity)
        data = payload.get("data")
        if not isinstance(data, list):
            return CatalogIdentityResult(identity)

        matching = []
        for item in data:
            if not isinstance(item, Mapping):
                continue
            number = str(item.get("number") or "").strip()
            set_payload = item.get("set")
            set_name = (
                str(set_payload.get("name") or "").strip()
                if isinstance(set_payload, Mapping)
                else ""
            )
            if _normalize(number) != _normalize(local_number):
                continue
            if _normalize(set_name) != _normalize(identity.set):
                continue
            if identity.card_name and _normalize(item.get("name")) != _normalize(
                identity.card_name
            ):
                continue
            matching.append(item)

        if len(matching) > 1:
            self.counters.ambiguous += 1
            return CatalogIdentityResult(identity, "POKEMON_TCG", False, True)
        if not matching:
            return CatalogIdentityResult(identity)

        item = matching[0]
        set_payload = item.get("set")
        set_name = (
            str(set_payload.get("name") or "").strip() or None
            if isinstance(set_payload, Mapping)
            else None
        )
        release_year = (
            _safe_year_from_release_date(set_payload.get("releaseDate"))
            if isinstance(set_payload, Mapping)
            else None
        )
        resolved = _with_catalog_identity(
            identity,
            card_name=str(item.get("name") or "").strip() or None,
            set_name=set_name,
            card_number=identity.card_number,
            year=release_year,
        )
        self.counters.pokemon_tcg_hits += 1
        return CatalogIdentityResult(resolved, "POKEMON_TCG", True, False)


class HybridPokemonCardResolver(MultilingualPokemonCardResolver):
    """TCGdex -> PokeTrace -> Pokemon TCG API identity chain."""

    _POKETRACE_US_LANGUAGES = {
        "english",
        "anglais",
        "en",
        "japanese",
        "japonais",
        "ja",
        "jp",
        "chinese",
        "chinois",
        "zh",
        "zh cn",
        "zh tw",
        "thai",
        "th",
        "indonesian",
        "id",
    }

    def __init__(
        self,
        *,
        poketrace_identity_resolver: PokeTraceIdentityResolver,
        session: Optional[requests.Session] = None,
        timeout_seconds: float = 12.0,
        pokemon_tcg_api_key: Optional[str] = None,
    ) -> None:
        super().__init__(
            session=session,
            timeout_seconds=timeout_seconds,
            pokemon_tcg_api_key=pokemon_tcg_api_key,
        )
        self.poketrace_identity = poketrace_identity_resolver

    def _poketrace_language_allowed(self, identity: CardIdentity) -> bool:
        return _normalize(identity.language) in self._POKETRACE_US_LANGUAGES

    def resolve_identity(self, identity: CardIdentity) -> CatalogIdentityResult:
        key = self._identity_key(identity)
        cached = self._identity_cache.get(key)
        if cached is not None:
            self.counters.cache_hits += 1
            return cached

        tcgdex = (
            self._resolve_tcgdex(identity)
            if identity.set and identity.card_number
            else CatalogIdentityResult(identity)
        )
        if not (identity.set and identity.card_number):
            self.counters.tcgdex_skipped_missing_fields += 1
        if tcgdex.blocking:
            self._identity_cache[key] = tcgdex
            return tcgdex
        if tcgdex.matched:
            self.counters.tcgdex_only_rescues += 1
            self.counters.tcgdex_poketrace_calls_avoided += 1
            self._identity_cache[key] = tcgdex
            return tcgdex

        poketrace = None
        supplied_core_fields = sum(
            bool(value)
            for value in (identity.card_name, identity.set, identity.card_number)
        )
        if (
            self._poketrace_language_allowed(identity)
            and supplied_core_fields >= 2
        ):
            poketrace = self.poketrace_identity.resolve_identity(identity)
            if poketrace.matched:
                result = CatalogIdentityResult(
                    poketrace.identity, "POKETRACE", True, False
                )
                self._identity_cache[key] = result
                return result

        if tcgdex.ambiguous or (poketrace is not None and poketrace.ambiguous):
            result = CatalogIdentityResult(identity, "MULTI_CATALOG", False, True)
            self._identity_cache[key] = result
            return result

        fallback = (
            self._resolve_pokemon_tcg(identity)
            if identity.set and identity.card_number
            else CatalogIdentityResult(identity)
        )
        if fallback.matched or fallback.ambiguous:
            if poketrace is not None:
                self.poketrace_identity.alias_cached_result(identity, fallback.identity)
            self._identity_cache[key] = fallback
            return fallback

        result = CatalogIdentityResult(identity)
        self.counters.no_match += 1
        self._identity_cache[key] = result
        return result


def render_card_catalog_counters(resolver: MultilingualPokemonCardResolver) -> str:
    counters = resolver.counters
    hybrid = isinstance(resolver, HybridPokemonCardResolver)
    return "\n".join(
        (
            "=== V5 CARD IDENTITY CATALOG ===",
            "primary: TCGdex multilingual (one set catalogue load per language/run)",
            (
                "fallback chain: PokeTrace US exact identity -> Pokémon TCG API"
                if hybrid
                else "fallback: Pokémon TCG API (English/unknown language only)"
            ),
            f"TCGdex requests: {counters.tcgdex_requests}",
            f"TCGdex hits: {counters.tcgdex_hits}",
            f"Pokémon TCG API requests: {counters.pokemon_tcg_requests}",
            f"Pokémon TCG API hits: {counters.pokemon_tcg_hits}",
            f"ambiguous catalog resolutions: {counters.ambiguous}",
            f"no catalog match: {counters.no_match}",
            f"catalog request failures: {counters.failures}",
            f"TCGdex transport failures: {counters.tcgdex_transport_failures}",
            f"TCGdex HTTP failures: {counters.tcgdex_http_failures}",
            f"TCGdex JSON failures: {counters.tcgdex_json_failures}",
            f"TCGdex set-catalog failures: {counters.tcgdex_set_catalog_failures}",
            f"TCGdex card-lookup failures: {counters.tcgdex_card_lookup_failures}",
            f"in-memory cache hits: {counters.cache_hits}",
            f"canonical identities changed by TCGdex - name: {counters.canonical_name_changes}",
            f"canonical identities changed by TCGdex - set: {counters.canonical_set_changes}",
            (
                "canonical identities changed by TCGdex - card number: "
                f"{counters.canonical_card_number_changes}"
            ),
            (
                "TCGdex numerator-only canonicalizations: "
                f"{counters.tcgdex_numerator_only_canonicalizations}"
            ),
            f"TCGdex denominator conflicts: {counters.tcgdex_denominator_conflicts}",
            (
                "TCGdex unique set-alias resolutions: "
                f"{counters.tcgdex_set_alias_unique_resolutions}"
            ),
            f"TCGdex ambiguous set aliases: {counters.tcgdex_ambiguous_set_aliases}",
            f"TCGdex-only rescues: {counters.tcgdex_only_rescues}",
            (
                "identities avoiding a PokeTrace call via TCGdex: "
                f"{counters.tcgdex_poketrace_calls_avoided}"
            ),
            (
                "TCGdex skipped - missing set/card number: "
                f"{counters.tcgdex_skipped_missing_fields}"
            ),
            f"TCGdex no-match - set: {counters.tcgdex_no_match_set}",
            f"TCGdex no-match - card: {counters.tcgdex_no_match_card}",
            (
                "TCGdex no-match - number conflict: "
                f"{counters.tcgdex_no_match_number_conflict}"
            ),
            (
                "TCGdex no-match - missing canonical name: "
                f"{counters.tcgdex_no_match_missing_name}"
            ),
            (
                "TCGdex no-match - returned set conflict: "
                f"{counters.tcgdex_no_match_set_conflict}"
            ),
            (
                "TCGdex deterministic localId alternates tried: "
                f"{counters.tcgdex_local_id_alternates_tried}"
            ),
            (
                "TCGdex deterministic localId alternate hits: "
                f"{counters.tcgdex_local_id_alternate_hits}"
            ),
            (
                "TCGdex direct-card fallbacks: "
                f"{counters.tcgdex_direct_card_fallbacks}"
            ),
            f"TCGdex direct-card hits: {counters.tcgdex_direct_card_hits}",
            f"TCGdex variant-impossible conflicts: {counters.tcgdex_variant_impossible}",
            (
                "TCGdex unsupported-language fallbacks to English metadata: "
                f"{counters.tcgdex_unsupported_language_fallbacks}"
            ),
            "language preserved as a first-class identity discriminator: YES",
            "persisted eBay records: 0",
        )
    )
