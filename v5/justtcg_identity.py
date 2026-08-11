from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Mapping, Optional, Sequence, Tuple

import requests

from .models import CardIdentity
from .poketrace_matching import (
    _card_number_parts,
    _normalize,
    _normalize_card_name,
    _normalize_card_number,
    _partial_card_number_equivalent,
    _set_similarity,
)
from .variant_semantics import semantics_from_identity, variant_compatibility


JUSTTCG_CARDS_URL = "https://api.justtcg.com/v1/cards"


@dataclass
class JustTCGCounters:
    queries: int = 0
    matches: int = 0
    ambiguous: int = 0
    no_match: int = 0
    skipped_insufficient: int = 0
    request_failures: int = 0
    rate_limited: int = 0
    candidates_received: int = 0
    rejected_name: int = 0
    rejected_set: int = 0
    rejected_number: int = 0
    rejected_language: int = 0
    rejected_variant: int = 0
    candidates_all_core_matched: int = 0
    variant_supported: int = 0


@dataclass(frozen=True)
class JustTCGIdentityResolution:
    identity: CardIdentity
    matched: bool = False
    ambiguous: bool = False
    card_id: Optional[str] = None


def _number_match(identity: CardIdentity, candidate_number: object, *, name_ok: bool, set_score: float) -> bool:
    expected = _normalize_card_number(identity.card_number)
    candidate = _normalize_card_number(candidate_number)
    if not expected:
        return True
    if not candidate:
        return False
    if expected == candidate:
        return True

    expected_num, expected_den = _card_number_parts(identity.card_number)
    candidate_num, candidate_den = _card_number_parts(candidate_number)
    if expected_num and expected_num == candidate_num:
        if expected_den is None or candidate_den is None:
            return bool(name_ok and set_score >= 0.86)
    return _partial_card_number_equivalent(
        identity.card_number,
        candidate_number,
        exact_name=name_ok,
        set_similarity=set_score,
    )


def _language_matches(expected: object, actual: object) -> bool:
    expected_norm = _normalize(expected)
    actual_norm = _normalize(actual)
    if not expected_norm:
        return True
    if not actual_norm:
        return False
    aliases = {
        "en": "english",
        "anglais": "english",
        "jp": "japanese",
        "ja": "japanese",
        "japonais": "japanese",
        "fr": "french",
        "francais": "french",
        "français": "french",
        "de": "german",
        "es": "spanish",
        "it": "italian",
        "pt": "portuguese",
    }
    return aliases.get(expected_norm, expected_norm) == aliases.get(actual_norm, actual_norm)


def _variant_required(identity: CardIdentity) -> bool:
    semantics, conflict = semantics_from_identity(identity)
    return bool(
        conflict
        or semantics.finish
        or semantics.edition
        or semantics.promo is True
        or semantics.special_finish
    )


def _candidate_variant_supported(identity: CardIdentity, card: Mapping[str, object]) -> tuple[bool, bool]:
    variants = card.get("variants")
    if not isinstance(variants, Sequence) or isinstance(variants, (str, bytes)):
        return (not _variant_required(identity), False)

    relevant_language = False
    relevant_variant = False
    for variant in variants:
        if not isinstance(variant, Mapping):
            continue
        if identity.language and not _language_matches(identity.language, variant.get("language")):
            continue
        relevant_language = True
        pseudo = {
            "variant": variant.get("printing"),
            "rarity": card.get("rarity"),
            "set": {"name": card.get("set_name"), "slug": card.get("set")},
        }
        compatibility = variant_compatibility(identity, pseudo)
        if compatibility.compatible:
            relevant_variant = True
            break

    if identity.language and not relevant_language:
        return False, False
    if _variant_required(identity) and not relevant_variant:
        return False, relevant_language
    return True, relevant_variant


def _resolved_identity(original: CardIdentity, card: Mapping[str, object]) -> CardIdentity:
    return replace(
        original,
        game=original.game or "Pokémon TCG",
        card_name=str(card.get("name") or "").strip() or original.card_name,
        set=str(card.get("set_name") or "").strip() or original.set,
        card_number=str(card.get("number") or "").strip() or original.card_number,
        rarity=original.rarity or (str(card.get("rarity") or "").strip() or None),
    )


class JustTCGIdentityResolver:
    """Strict card-identity resolver intended for same-sample benchmarking.

    It deliberately does not expose price data to V5 economics yet. One GET per
    resolvable identity uses JustTCG's stable v1 search + card-number filter,
    then every candidate is revalidated locally against name, set, number,
    language and printing semantics.
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        session: Optional[requests.Session] = None,
        timeout_seconds: float = 12.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("JUSTTCG_API_KEY", "").strip()
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds
        self.counters = JustTCGCounters()
        self._cache: dict[Tuple[str, ...], JustTCGIdentityResolution] = {}

    @staticmethod
    def _key(identity: CardIdentity) -> Tuple[str, ...]:
        return (
            _normalize_card_name(identity.card_name),
            _normalize(identity.set),
            _normalize_card_number(identity.card_number),
            _normalize(identity.language),
            _normalize(identity.variant),
            _normalize(identity.finish),
            _normalize(identity.edition),
        )

    def resolve_identity(self, identity: CardIdentity) -> JustTCGIdentityResolution:
        if not self.api_key:
            return JustTCGIdentityResolution(identity)
        supplied = sum(bool(value) for value in (identity.card_name, identity.set, identity.card_number))
        if supplied < 2 or not identity.card_name:
            self.counters.skipped_insufficient += 1
            return JustTCGIdentityResolution(identity)

        key = self._key(identity)
        if key in self._cache:
            return self._cache[key]

        params = {
            "game": "pokemon-japan" if _normalize(identity.language) in {"japanese", "japonais", "ja", "jp"} else "pokemon",
            "q": str(identity.card_name).strip(),
            "limit": "20",
            "include_null_prices": "true",
            "include_price_history": "false",
            "include_statistics": "false",
        }
        numerator, _denominator = _card_number_parts(identity.card_number)
        if numerator:
            params["number"] = numerator

        self.counters.queries += 1
        try:
            response = self.session.get(
                JUSTTCG_CARDS_URL,
                headers={"Accept": "application/json", "x-api-key": self.api_key},
                params=params,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException:
            self.counters.request_failures += 1
            result = JustTCGIdentityResolution(identity)
            self._cache[key] = result
            return result

        if response.status_code == 429:
            self.counters.rate_limited += 1
            result = JustTCGIdentityResolution(identity)
            self._cache[key] = result
            return result
        if response.status_code != 200:
            self.counters.request_failures += 1
            result = JustTCGIdentityResolution(identity)
            self._cache[key] = result
            return result
        try:
            payload = response.json()
        except ValueError:
            self.counters.request_failures += 1
            result = JustTCGIdentityResolution(identity)
            self._cache[key] = result
            return result

        data = payload.get("data") if isinstance(payload, Mapping) else None
        candidates = (
            tuple(item for item in data if isinstance(item, Mapping))
            if isinstance(data, Sequence) and not isinstance(data, (str, bytes))
            else ()
        )
        self.counters.candidates_received += len(candidates)

        accepted = []
        for card in candidates:
            name_ok = _normalize_card_name(card.get("name")) == _normalize_card_name(identity.card_name)
            if not name_ok:
                self.counters.rejected_name += 1
                continue
            set_score = _set_similarity(identity.set, card.get("set_name"), card.get("set"))
            if identity.set and set_score < 0.66:
                self.counters.rejected_set += 1
                continue
            if identity.card_number and not _number_match(identity, card.get("number"), name_ok=name_ok, set_score=set_score):
                self.counters.rejected_number += 1
                continue

            self.counters.candidates_all_core_matched += 1
            variant_ok, variant_supported = _candidate_variant_supported(identity, card)
            if not variant_ok:
                variants = card.get("variants")
                if identity.language and isinstance(variants, Sequence):
                    languages = [
                        item.get("language")
                        for item in variants
                        if isinstance(item, Mapping)
                    ]
                    if languages and not any(_language_matches(identity.language, value) for value in languages):
                        self.counters.rejected_language += 1
                        continue
                self.counters.rejected_variant += 1
                continue
            self.counters.variant_supported += int(variant_supported)
            accepted.append(card)

        if len(accepted) > 1:
            self.counters.ambiguous += 1
            result = JustTCGIdentityResolution(identity, ambiguous=True)
        elif not accepted:
            self.counters.no_match += 1
            result = JustTCGIdentityResolution(identity)
        else:
            card = accepted[0]
            self.counters.matches += 1
            result = JustTCGIdentityResolution(
                _resolved_identity(identity, card),
                matched=True,
                card_id=str(card.get("uuid") or card.get("id") or "").strip() or None,
            )
        self._cache[key] = result
        return result


def render_justtcg_counters(resolver: JustTCGIdentityResolver) -> str:
    c = resolver.counters
    return "\n".join(
        (
            "=== V5 JUSTTCG IDENTITY BENCHMARK ===",
            "role: same-sample second opinion only; no economic value accepted",
            f"queries: {c.queries}",
            f"matches: {c.matches}",
            f"ambiguous: {c.ambiguous}",
            f"no match: {c.no_match}",
            f"skipped insufficient: {c.skipped_insufficient}",
            f"request failures: {c.request_failures}",
            f"rate limited: {c.rate_limited}",
            f"candidates received: {c.candidates_received}",
            f"candidates all core matched: {c.candidates_all_core_matched}",
            f"rejected name: {c.rejected_name}",
            f"rejected set: {c.rejected_set}",
            f"rejected number: {c.rejected_number}",
            f"rejected language: {c.rejected_language}",
            f"rejected variant: {c.rejected_variant}",
            f"variant supported: {c.variant_supported}",
            "persisted cards/listings/prices: 0",
        )
    )
