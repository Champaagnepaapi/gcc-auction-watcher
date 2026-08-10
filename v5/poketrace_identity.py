from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Mapping, Optional, Sequence, Tuple

from .market_values.poketrace import (
    POKETRACE_MATCHED,
    POKETRACE_NO_MATCH,
    PokeTraceProvider,
    PokeTraceSnapshot,
    _identity_key,
    _poketrace_game,
    _us_market_values,
)
from .market_values.poketrace_free import FreeTierPokeTraceProvider
from .models import CardIdentity


@dataclass
class PokeTraceIdentityCounters:
    queries: int = 0
    matches: int = 0
    ambiguous: int = 0
    no_match: int = 0
    cache_hits: int = 0
    request_failures: int = 0
    rate_limited: int = 0
    primed_market_snapshots: int = 0


@dataclass(frozen=True)
class PokeTraceIdentityResolution:
    identity: CardIdentity
    matched: bool = False
    ambiguous: bool = False
    card_id: Optional[str] = None


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _normalize_card_number(value: object) -> str:
    compact = re.sub(r"\s+", "", str(value or "")).lstrip("#")
    parts = compact.split("/", 1)

    def canonical(part: str) -> str:
        match = re.fullmatch(r"0*(\d+)([A-Za-z]*)", part)
        if not match:
            return _normalize(part).replace(" ", "")
        return f"{int(match.group(1))}{match.group(2).casefold()}"

    return "/".join(canonical(part) for part in parts)


def _slugify(value: object) -> str:
    return "-".join(_normalize(value).split())


def _numeric_tokens(value: object) -> frozenset[str]:
    return frozenset(re.findall(r"\d+(?:\.\d+)?", _normalize(value)))


def _set_similarity(expected: object, candidate_name: object, candidate_slug: object) -> float:
    expected_norm = _normalize(expected)
    candidate_norm = _normalize(candidate_name)
    expected_slug = _slugify(expected)
    candidate_slug_norm = _slugify(candidate_slug)
    if not expected_norm:
        return 1.0
    if expected_norm == candidate_norm or (
        expected_slug and expected_slug == candidate_slug_norm
    ):
        return 1.0

    expected_numbers = _numeric_tokens(expected)
    candidate_numbers = _numeric_tokens(candidate_name)
    if expected_numbers and candidate_numbers and expected_numbers != candidate_numbers:
        return 0.0

    expected_tokens = set(expected_norm.split())
    candidate_tokens = set(candidate_norm.split())
    if not expected_tokens or not candidate_tokens:
        return 0.0

    intersection = len(expected_tokens & candidate_tokens)
    union = len(expected_tokens | candidate_tokens)
    jaccard = intersection / union if union else 0.0

    # Safe alias case such as "Pokemon TCG Scarlet Violet 151" -> "151".
    shorter, longer = sorted((expected_tokens, candidate_tokens), key=len)
    containment = bool(shorter) and shorter.issubset(longer)
    if containment and intersection:
        return max(jaccard, 0.86)
    return jaccard


def _variant_family(value: object) -> str:
    normalized = _normalize(value)
    aliases = {
        "holo": "holofoil",
        "holographic": "holofoil",
        "holofoil": "holofoil",
        "reverse holo": "reverse holofoil",
        "reverse holographic": "reverse holofoil",
        "reverse holofoil": "reverse holofoil",
        "normal": "standard",
        "non holo": "standard",
        "standard": "standard",
    }
    return aliases.get(normalized, normalized)


def _candidate_score(identity: CardIdentity, candidate: Mapping[str, object]) -> Optional[float]:
    product_type = _normalize(candidate.get("productType"))
    if product_type and product_type != "single":
        return None

    expected_number = _normalize_card_number(identity.card_number)
    candidate_number = _normalize_card_number(candidate.get("cardNumber"))
    if expected_number and candidate_number != expected_number:
        return None

    expected_name = _normalize(identity.card_name)
    candidate_name = _normalize(candidate.get("name"))
    if expected_name and candidate_name != expected_name:
        return None

    set_payload = candidate.get("set")
    set_name = set_payload.get("name") if isinstance(set_payload, Mapping) else None
    set_slug = set_payload.get("slug") if isinstance(set_payload, Mapping) else None
    set_similarity = _set_similarity(identity.set, set_name, set_slug)
    if identity.set and set_similarity < 0.66:
        return None

    expected_variant = _variant_family(identity.variant)
    candidate_variant = _variant_family(candidate.get("variant"))
    if expected_variant and candidate_variant and expected_variant != candidate_variant:
        return None

    # Missing card name is only safe when set + number identify one candidate.
    if not expected_name and (not expected_number or set_similarity < 0.86):
        return None

    score = 4.0 if expected_name else 0.0
    score += 4.0 if expected_number else 0.0
    score += set_similarity * 3.0
    if expected_variant and candidate_variant == expected_variant:
        score += 1.0
    return score


def _resolved_identity(original: CardIdentity, card: Mapping[str, object]) -> CardIdentity:
    set_payload = card.get("set")
    set_name = (
        str(set_payload.get("name") or "").strip() or original.set
        if isinstance(set_payload, Mapping)
        else original.set
    )
    return replace(
        original,
        game=original.game or "Pokémon TCG",
        card_name=str(card.get("name") or "").strip() or original.card_name,
        set=set_name,
        variant=original.variant or (str(card.get("variant") or "").strip() or None),
        rarity=original.rarity or (str(card.get("rarity") or "").strip() or None),
    )


class PokeTraceIdentityResolver:
    """Use the PokeTrace cards catalogue as a conservative identity resolver.

    The same US card response is injected into the existing PokeTrace market
    cache. A successful identity lookup therefore also supplies raw market data
    later in the V5 pipeline without spending a second Free-tier request.
    """

    def __init__(self, provider: PokeTraceProvider) -> None:
        self.provider = provider
        self.counters = PokeTraceIdentityCounters()
        self._cache: dict[Tuple[str, ...], PokeTraceIdentityResolution] = {}

    def resolve_identity(self, identity: CardIdentity) -> PokeTraceIdentityResolution:
        if not self.provider.config.enabled or not self.provider.config.api_key:
            return PokeTraceIdentityResolution(identity)
        if not identity.card_number:
            return PokeTraceIdentityResolution(identity)

        key = _identity_key(identity)
        cached = self._cache.get(key)
        if cached is not None:
            self.counters.cache_hits += 1
            return cached

        self.counters.queries += 1
        self._progress(f"PokeTrace identity {self.counters.queries}: query")
        payload = self._request(identity)
        if payload is None:
            result = PokeTraceIdentityResolution(identity)
            self._cache[key] = result
            self._prime_no_match(identity)
            return result

        data = payload.get("data")
        candidates = (
            tuple(item for item in data if isinstance(item, Mapping))
            if isinstance(data, Sequence) and not isinstance(data, (str, bytes))
            else ()
        )
        scored = []
        for candidate in candidates:
            score = _candidate_score(identity, candidate)
            if score is not None:
                scored.append((score, candidate))

        if not scored:
            self.counters.no_match += 1
            result = PokeTraceIdentityResolution(identity)
            self._cache[key] = result
            self._prime_no_match(identity)
            self._progress(f"PokeTrace identity {self.counters.queries}: no match")
            return result

        best_score = max(score for score, _candidate in scored)
        best = tuple(candidate for score, candidate in scored if score == best_score)
        if len(best) != 1:
            self.counters.ambiguous += 1
            result = PokeTraceIdentityResolution(identity, ambiguous=True)
            self._cache[key] = result
            self._progress(f"PokeTrace identity {self.counters.queries}: ambiguous")
            return result

        card = best[0]
        resolved = _resolved_identity(identity, card)
        card_id = str(card.get("id") or "").strip() or None
        result = PokeTraceIdentityResolution(
            resolved,
            matched=bool(resolved.card_name and resolved.set and resolved.card_number),
            card_id=card_id,
        )
        if not result.matched:
            self.counters.no_match += 1
            self._cache[key] = PokeTraceIdentityResolution(identity)
            self._prime_no_match(identity)
            return self._cache[key]

        self.counters.matches += 1
        self._cache[key] = result
        self._cache[_identity_key(resolved)] = result
        self._prime_market_snapshot(identity, resolved, card)
        self._progress(f"PokeTrace identity {self.counters.queries}: exact")
        return result

    def alias_cached_result(self, source: CardIdentity, target: CardIdentity) -> None:
        source_result = self._cache.get(_identity_key(source))
        if source_result is not None and not source_result.matched:
            self._cache[_identity_key(target)] = source_result
            if not source_result.ambiguous:
                self._prime_no_match(target)

    def _request(self, identity: CardIdentity) -> Optional[Mapping[str, object]]:
        self.provider._respect_rate_limit()
        params = {
            "market": "US",
            "limit": str(self.provider.config.result_limit),
            "product_type": "single",
        }
        if identity.card_name:
            params["search"] = str(identity.card_name).strip()
        if identity.card_number:
            params["card_number"] = str(identity.card_number).strip()
        # PokeTrace documents `set` as a set slug. Only use it when the name is
        # absent; with a card name present we prefer a wider result set and do
        # conservative local set matching so eBay aliases do not zero results.
        if identity.set and not identity.card_name:
            params["set"] = _slugify(identity.set)
        game = _poketrace_game(identity.language)
        if game:
            params["game"] = game

        headers = {
            "Accept": "application/json",
            "X-API-Key": self.provider.config.api_key or "",
        }
        try:
            self.provider.counters.live_calls += 1
            response = self.provider.session.get(
                "https://api.poketrace.com/v1/cards",
                headers=headers,
                params=params,
                timeout=self.provider.config.timeout_seconds,
            )
        except Exception:
            self.provider.counters.request_failures += 1
            self.counters.request_failures += 1
            return None

        status = getattr(response, "status_code", None)
        if status == 429:
            self.provider.counters.rate_limited += 1
            self.counters.rate_limited += 1
            return None
        if status != 200:
            self.provider.counters.request_failures += 1
            self.counters.request_failures += 1
            return None
        try:
            payload = response.json()
        except Exception:
            self.provider.counters.request_failures += 1
            self.counters.request_failures += 1
            return None
        return payload if isinstance(payload, Mapping) else None

    def _prime_market_snapshot(
        self,
        original: CardIdentity,
        resolved: CardIdentity,
        card: Mapping[str, object],
    ) -> None:
        values = _us_market_values(resolved, card)
        if isinstance(self.provider, FreeTierPokeTraceProvider) and values is not None:
            values = replace(
                values,
                source="PokeTrace Free US: eBay + TCGPlayer raw",
                grade8_generic_value=None,
                grade9_generic_value=None,
                psa10_value=None,
                notes=(
                    "Free-tier validation: identity and US raw price reused from one response",
                    "No EU/CardMarket request performed",
                    "No graded value accepted from the Free tier",
                ),
                limitations=(
                    "PokeTrace Free: 250 requests/day",
                    "PokeTrace Free burst: 1 request per 2 seconds",
                    "EU/CardMarket and graded tiers require Pro or higher",
                ),
            )
        snapshot = PokeTraceSnapshot(
            POKETRACE_MATCHED if values is not None else POKETRACE_NO_MATCH,
            us_values=values,
            cardmarket=None,
        )
        for identity in (original, resolved):
            self.provider._cache[("free",) + _identity_key(identity)] = snapshot
        self.counters.primed_market_snapshots += 1

    def _prime_no_match(self, identity: CardIdentity) -> None:
        if isinstance(self.provider, FreeTierPokeTraceProvider):
            self.provider._cache[("free",) + _identity_key(identity)] = PokeTraceSnapshot(
                POKETRACE_NO_MATCH
            )

    @staticmethod
    def _progress(message: str) -> None:
        if os.getenv("V5_PROGRESS_LOGS", "false").strip().casefold() == "true":
            print(f"[V5] {message}", flush=True)


def render_poketrace_identity_counters(resolver: PokeTraceIdentityResolver) -> str:
    counters = resolver.counters
    return "\n".join(
        (
            "=== V5 POKETRACE IDENTITY ===",
            "role: fallback identity resolver after TCGdex, before Pokemon TCG API",
            f"queries: {counters.queries}",
            f"exact matches: {counters.matches}",
            f"ambiguous: {counters.ambiguous}",
            f"no match: {counters.no_match}",
            f"cache hits: {counters.cache_hits}",
            f"request failures: {counters.request_failures}",
            f"rate limited: {counters.rate_limited}",
            f"market snapshots primed from identity response: {counters.primed_market_snapshots}",
            "extra PokeTrace request needed for a primed market match: 0",
            "persisted eBay records: 0",
        )
    )
