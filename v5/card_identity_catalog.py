from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Mapping, Optional, Sequence, Tuple

import requests

from .ebay import CardNameLookupResult, SetNumberCardNameResolver
from .models import CardIdentity


TCGDEX_BASE = "https://api.tcgdex.net/v2"
POKEMON_TCG_BASE = "https://api.pokemontcg.io/v2"


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
    "korean": "ko",
    "coreen": "ko",
    "coréen": "ko",
    "ko": "ko",
    "portuguese": "pt",
    "portugais": "pt",
    "pt": "pt",
    "chinese": "zh-cn",
    "chinois": "zh-cn",
    "zh-cn": "zh-cn",
    "traditional chinese": "zh-tw",
    "zh-tw": "zh-tw",
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


@dataclass(frozen=True)
class CatalogIdentityResult:
    identity: CardIdentity
    source: str = "NONE"
    matched: bool = False
    ambiguous: bool = False


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


def _safe_year_from_release_date(value: object) -> Optional[int]:
    match = re.match(r"\s*((?:19|20)\d{2})", str(value or ""))
    return int(match.group(1)) if match else None


def _with_catalog_identity(
    original: CardIdentity,
    *,
    card_name: Optional[str],
    set_name: Optional[str],
    year: Optional[int],
) -> CardIdentity:
    return replace(
        original,
        game=original.game or "Pokémon TCG",
        card_name=(card_name or original.card_name),
        set=(set_name or original.set),
        year=(original.year if original.year is not None else year),
    )


class MultilingualPokemonCardResolver(SetNumberCardNameResolver):
    """Resolve eBay card identity through TCGdex, then Pokémon TCG API.

    TCGdex is authoritative for this resolver because it is multilingual. The
    Pokémon TCG API is used only for English/unknown-language fallbacks; it is
    deliberately not used to overwrite a known French/Japanese/etc language.

    All caches are in-memory for one run. No eBay payload, item id, title, URL,
    seller, image or price is persisted.
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
        self._card_cache: dict[Tuple[str, str, str], Optional[Mapping[str, object]]] = {}

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
            return CatalogIdentityResult(identity)
        key = (
            _normalize(identity.set),
            _normalize(identity.card_number),
            _normalize(identity.language),
            _normalize(identity.card_name),
            str(identity.year or ""),
            _normalize(identity.variant),
        )
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
            return None
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            self.counters.failures += 1
            return None
        try:
            return response.json()
        except ValueError:
            self.counters.failures += 1
            return None

    def _tcgdex_sets(self, language: str, set_name: str) -> Tuple[Tuple[str, str], ...]:
        cache_key = (language, _normalize(set_name))
        if cache_key in self._set_cache:
            return self._set_cache[cache_key]
        payload = self._get_json(
            f"{TCGDEX_BASE}/{language}/sets",
            params={"name": set_name},
            provider="TCGDEX",
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
        self._set_cache[cache_key] = result
        return result

    def _tcgdex_card(
        self, language: str, set_id: str, local_number: str
    ) -> Optional[Mapping[str, object]]:
        cache_key = (language, set_id, local_number)
        if cache_key in self._card_cache:
            return self._card_cache[cache_key]
        payload = self._get_json(
            f"{TCGDEX_BASE}/{language}/sets/{set_id}/{local_number}",
            provider="TCGDEX",
        )
        card = payload if isinstance(payload, Mapping) else None
        self._card_cache[cache_key] = card
        return card

    def _resolve_tcgdex(self, identity: CardIdentity) -> CatalogIdentityResult:
        target_language = _language_code(identity.language) or "en"
        lookup_languages = tuple(dict.fromkeys((target_language, "en", "fr")))
        normalized_set = _normalize(identity.set)
        exact_ids: dict[str, str] = {}
        loose_ids: dict[str, str] = {}

        for language in lookup_languages:
            for set_id, name in self._tcgdex_sets(language, identity.set or ""):
                loose_ids.setdefault(set_id, name)
                if _normalize(name) == normalized_set:
                    exact_ids.setdefault(set_id, name)

        candidate_ids = exact_ids or loose_ids
        if len(candidate_ids) != 1:
            if len(candidate_ids) > 1:
                self.counters.ambiguous += 1
                return CatalogIdentityResult(identity, "TCGDEX", False, True)
            return CatalogIdentityResult(identity)

        set_id = next(iter(candidate_ids))
        local_number = _local_card_number(identity.card_number or "")
        if not local_number:
            return CatalogIdentityResult(identity)

        card = self._tcgdex_card(target_language, set_id, local_number)
        if card is None and target_language != "en":
            card = self._tcgdex_card("en", set_id, local_number)
        if card is None:
            return CatalogIdentityResult(identity)

        card_name = str(card.get("name") or "").strip() or None
        card_local_id = str(card.get("localId") or "").strip()
        if card_local_id and _normalize(card_local_id) != _normalize(local_number):
            self.counters.ambiguous += 1
            return CatalogIdentityResult(identity, "TCGDEX", False, True)

        set_payload = card.get("set")
        card_set_name = None
        release_year = None
        if isinstance(set_payload, Mapping):
            card_set_name = str(set_payload.get("name") or "").strip() or None
            release_year = _safe_year_from_release_date(set_payload.get("releaseDate"))
        if card_set_name is None:
            card_set_name = candidate_ids.get(set_id)

        if not card_name:
            return CatalogIdentityResult(identity)
        resolved = _with_catalog_identity(
            identity,
            card_name=card_name,
            set_name=card_set_name,
            year=release_year,
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
            year=release_year,
        )
        self.counters.pokemon_tcg_hits += 1
        return CatalogIdentityResult(resolved, "POKEMON_TCG", True, False)


def render_card_catalog_counters(resolver: MultilingualPokemonCardResolver) -> str:
    counters = resolver.counters
    return "\n".join(
        (
            "=== V5 CARD IDENTITY CATALOG ===",
            "primary: TCGdex multilingual",
            "fallback: Pokémon TCG API (English/unknown language only)",
            f"TCGdex requests: {counters.tcgdex_requests}",
            f"TCGdex hits: {counters.tcgdex_hits}",
            f"Pokémon TCG API requests: {counters.pokemon_tcg_requests}",
            f"Pokémon TCG API hits: {counters.pokemon_tcg_hits}",
            f"ambiguous catalog resolutions: {counters.ambiguous}",
            f"no catalog match: {counters.no_match}",
            f"catalog request failures: {counters.failures}",
            f"in-memory cache hits: {counters.cache_hits}",
            "language preserved as a first-class identity discriminator: YES",
            "persisted eBay records: 0",
        )
    )
