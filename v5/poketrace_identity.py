from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Mapping, Optional, Sequence, Tuple

from .market_values.poketrace import (
    POKETRACE_DISABLED,
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


REQUEST_OK = "OK"
REQUEST_ERROR = "ERROR"
REQUEST_RATE_LIMITED = "RATE_LIMITED"

REJECT_PRODUCT_TYPE = "product_type"
REJECT_CARD_NUMBER = "card_number"
REJECT_CARD_NAME = "card_name"
REJECT_SET = "set"
REJECT_VARIANT = "variant"
REJECT_INSUFFICIENT = "insufficient"


@dataclass
class PokeTraceIdentityCounters:
    queries: int = 0
    search_attempts: int = 0
    fallback_searches: int = 0
    matches: int = 0
    ambiguous: int = 0
    no_match: int = 0
    cache_hits: int = 0
    request_failures: int = 0
    rate_limited: int = 0
    retry_attempts: int = 0
    api_empty_results: int = 0
    candidates_received: int = 0
    rejected_product_type: int = 0
    rejected_card_number: int = 0
    rejected_card_name: int = 0
    rejected_set: int = 0
    rejected_variant: int = 0
    rejected_insufficient: int = 0
    partial_number_candidates: int = 0
    partial_number_matches: int = 0
    primed_market_snapshots: int = 0
    card_numbers_recovered: int = 0
    card_names_recovered: int = 0
    sets_recovered: int = 0


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


def _card_number_parts(value: object) -> tuple[str, Optional[str]]:
    normalized = _normalize_card_number(value)
    if not normalized:
        return "", None
    if "/" not in normalized:
        return normalized, None
    numerator, denominator = normalized.split("/", 1)
    return numerator, denominator or None


def _partial_card_number_equivalent(
    expected: object,
    candidate: object,
    *,
    exact_name: bool,
    set_similarity: float,
) -> bool:
    """Accept numerator-only vs full collector number under strong identity.

    eBay structured aspects sometimes expose only the collector numerator while
    PokeTrace returns the canonical numerator/denominator. This is not a fuzzy
    number match: the normalized numerator must be identical, exactly one side
    must omit the denominator, the card name must be exact, and the set must be
    a strong normalized/alias match. Two conflicting full numbers never pass.
    """

    expected_number = _normalize_card_number(expected)
    candidate_number = _normalize_card_number(candidate)
    if not expected_number or not candidate_number:
        return False
    if expected_number == candidate_number:
        return False

    expected_numerator, expected_denominator = _card_number_parts(expected)
    candidate_numerator, candidate_denominator = _card_number_parts(candidate)
    if not expected_numerator or expected_numerator != candidate_numerator:
        return False
    if (expected_denominator is None) == (candidate_denominator is None):
        return False
    return exact_name and set_similarity >= 0.86


def _numeric_tokens(value: object) -> frozenset[str]:
    return frozenset(re.findall(r"\d+(?:\.\d+)?", _normalize(value)))


def _set_similarity(expected: object, candidate_name: object, candidate_slug: object) -> float:
    expected_norm = _normalize(expected)
    candidate_norm = _normalize(candidate_name)
    candidate_slug_norm = _normalize(candidate_slug)
    if not expected_norm:
        return 1.0
    if expected_norm == candidate_norm or expected_norm == candidate_slug_norm:
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


def _candidate_uses_partial_number(identity: CardIdentity, candidate: Mapping[str, object]) -> bool:
    expected_name = _normalize(identity.card_name)
    candidate_name = _normalize(candidate.get("name"))
    set_payload = candidate.get("set")
    set_name = set_payload.get("name") if isinstance(set_payload, Mapping) else None
    set_slug = set_payload.get("slug") if isinstance(set_payload, Mapping) else None
    return _partial_card_number_equivalent(
        identity.card_number,
        candidate.get("cardNumber"),
        exact_name=bool(expected_name and expected_name == candidate_name),
        set_similarity=_set_similarity(identity.set, set_name, set_slug),
    )


def _candidate_score_and_rejection(
    identity: CardIdentity, candidate: Mapping[str, object]
) -> tuple[Optional[float], Optional[str]]:
    product_type = _normalize(candidate.get("productType"))
    if product_type and product_type != "single":
        return None, REJECT_PRODUCT_TYPE

    expected_name = _normalize(identity.card_name)
    candidate_name = _normalize(candidate.get("name"))
    if expected_name and candidate_name != expected_name:
        return None, REJECT_CARD_NAME
    exact_name = bool(expected_name and candidate_name == expected_name)

    set_payload = candidate.get("set")
    set_name = set_payload.get("name") if isinstance(set_payload, Mapping) else None
    set_slug = set_payload.get("slug") if isinstance(set_payload, Mapping) else None
    set_similarity = _set_similarity(identity.set, set_name, set_slug)
    if identity.set and set_similarity < 0.66:
        return None, REJECT_SET

    expected_number = _normalize_card_number(identity.card_number)
    candidate_number = _normalize_card_number(candidate.get("cardNumber"))
    number_exact = bool(expected_number and candidate_number == expected_number)
    number_partial = _partial_card_number_equivalent(
        identity.card_number,
        candidate.get("cardNumber"),
        exact_name=exact_name,
        set_similarity=set_similarity,
    )
    if expected_number and not (number_exact or number_partial):
        return None, REJECT_CARD_NUMBER

    expected_variant = _variant_family(identity.variant)
    candidate_variant = _variant_family(candidate.get("variant"))
    if expected_variant and candidate_variant and expected_variant != candidate_variant:
        return None, REJECT_VARIANT

    # We allow PokeTrace to recover one missing discriminator only when the
    # remaining pair is strong enough and the candidate is unique. This is how
    # we can rescue eBay records missing card_number without guessing.
    supplied_core = sum(bool(value) for value in (identity.card_name, identity.set, identity.card_number))
    if supplied_core < 2:
        return None, REJECT_INSUFFICIENT
    if not expected_name and (not expected_number or set_similarity < 0.86):
        return None, REJECT_INSUFFICIENT
    if not expected_number and (not expected_name or not identity.set or set_similarity < 0.86):
        return None, REJECT_INSUFFICIENT

    score = 4.0 if expected_name else 0.0
    if number_exact:
        score += 4.0
    elif number_partial:
        # Strong but deliberately below a full collector-number equality.
        score += 3.0
    score += set_similarity * 3.0
    if expected_variant and candidate_variant == expected_variant:
        score += 1.0
    # A recovered missing number/name/set must still rank below a fully
    # specified exact identity, but can be accepted if it is the only best hit.
    score += 0.5 * supplied_core
    return score, None


def _resolved_identity(original: CardIdentity, card: Mapping[str, object]) -> CardIdentity:
    set_payload = card.get("set")
    set_name = (
        str(set_payload.get("name") or "").strip() or original.set
        if isinstance(set_payload, Mapping)
        else original.set
    )
    card_number = str(card.get("cardNumber") or "").strip() or original.card_number
    return replace(
        original,
        game=original.game or "Pokémon TCG",
        card_name=str(card.get("name") or "").strip() or original.card_name,
        set=set_name,
        card_number=card_number,
        variant=original.variant or (str(card.get("variant") or "").strip() or None),
        rarity=original.rarity or (str(card.get("rarity") or "").strip() or None),
    )


def _candidate_key(candidate: Mapping[str, object]) -> Tuple[str, ...]:
    set_payload = candidate.get("set")
    set_name = set_payload.get("name") if isinstance(set_payload, Mapping) else None
    return (
        str(candidate.get("id") or "").strip(),
        _normalize(candidate.get("name")),
        _normalize_card_number(candidate.get("cardNumber")),
        _normalize(set_name),
        _normalize(candidate.get("variant")),
    )


def _search_strings(identity: CardIdentity) -> Tuple[str, ...]:
    name = str(identity.card_name or "").strip()
    number = str(identity.card_number or "").strip()
    set_name = str(identity.set or "").strip()

    primary_parts = [value for value in (name, number, set_name) if value]
    strategies = []
    if primary_parts:
        strategies.append(" ".join(primary_parts))

    # Second search deliberately removes the discriminator most likely to be
    # formatted differently by the upstream marketplace. Local validation
    # stays strict, so this broadens retrieval without broadening acceptance.
    if name:
        strategies.append(name)
    elif number:
        strategies.append(number)
    elif set_name:
        strategies.append(set_name)

    return tuple(dict.fromkeys(value for value in strategies if value))


class PokeTraceIdentityResolver:
    """Conservative PokeTrace resolver with broad retrieval + strict local match."""

    def __init__(self, provider: PokeTraceProvider) -> None:
        self.provider = provider
        self.counters = PokeTraceIdentityCounters()
        self._cache: dict[Tuple[str, ...], PokeTraceIdentityResolution] = {}

    def resolve_identity(self, identity: CardIdentity) -> PokeTraceIdentityResolution:
        if not self.provider.config.enabled or not self.provider.config.api_key:
            return PokeTraceIdentityResolution(identity)
        if sum(bool(value) for value in (identity.card_name, identity.set, identity.card_number)) < 2:
            return PokeTraceIdentityResolution(identity)

        key = _identity_key(identity)
        cached = self._cache.get(key)
        if cached is not None:
            self.counters.cache_hits += 1
            return cached

        self.counters.queries += 1
        self._progress(f"PokeTrace identity {self.counters.queries}: query")
        seen_candidates: set[Tuple[str, ...]] = set()

        for index, search_text in enumerate(_search_strings(identity)):
            if index > 0:
                self.counters.fallback_searches += 1
                self._progress(
                    f"PokeTrace identity {self.counters.queries}: broad fallback"
                )
            payload, request_status = self._request(identity, search_text)
            if request_status != REQUEST_OK or payload is None:
                result = PokeTraceIdentityResolution(identity)
                self._cache[key] = result
                self._prime_unavailable(identity)
                self._progress(
                    f"PokeTrace identity {self.counters.queries}: {request_status.casefold()}"
                )
                return result

            data = payload.get("data")
            candidates = (
                tuple(item for item in data if isinstance(item, Mapping))
                if isinstance(data, Sequence) and not isinstance(data, (str, bytes))
                else ()
            )
            if not candidates:
                self.counters.api_empty_results += 1
                continue

            scored = []
            for candidate in candidates:
                candidate_key = _candidate_key(candidate)
                if candidate_key in seen_candidates:
                    continue
                seen_candidates.add(candidate_key)
                self.counters.candidates_received += 1
                score, rejection = _candidate_score_and_rejection(identity, candidate)
                if rejection is not None:
                    self._count_rejection(rejection)
                    continue
                if score is not None:
                    if _candidate_uses_partial_number(identity, candidate):
                        self.counters.partial_number_candidates += 1
                    scored.append((score, candidate))

            if not scored:
                continue

            best_score = max(score for score, _candidate in scored)
            best = tuple(candidate for score, candidate in scored if score == best_score)
            if len(best) != 1:
                self.counters.ambiguous += 1
                self.provider.counters.ambiguous += 1
                result = PokeTraceIdentityResolution(identity, ambiguous=True)
                self._cache[key] = result
                self._prime_unavailable(identity)
                self._progress(f"PokeTrace identity {self.counters.queries}: ambiguous")
                return result

            card = best[0]
            used_partial_number = _candidate_uses_partial_number(identity, card)
            resolved = _resolved_identity(identity, card)
            card_id = str(card.get("id") or "").strip() or None
            result = PokeTraceIdentityResolution(
                resolved,
                matched=bool(resolved.card_name and resolved.set and resolved.card_number),
                card_id=card_id,
            )
            if not result.matched:
                self._count_rejection(REJECT_INSUFFICIENT)
                continue

            self.counters.matches += 1
            self.provider.counters.us_matches += 1
            if used_partial_number:
                self.counters.partial_number_matches += 1
            if not identity.card_number and resolved.card_number:
                self.counters.card_numbers_recovered += 1
            if not identity.card_name and resolved.card_name:
                self.counters.card_names_recovered += 1
            if not identity.set and resolved.set:
                self.counters.sets_recovered += 1
            self._cache[key] = result
            self._cache[_identity_key(resolved)] = result
            self._prime_market_snapshot(identity, resolved, card)
            self._progress(f"PokeTrace identity {self.counters.queries}: exact")
            return result

        self.counters.no_match += 1
        self.provider.counters.no_match += 1
        result = PokeTraceIdentityResolution(identity)
        self._cache[key] = result
        self._prime_no_match(identity)
        self._progress(f"PokeTrace identity {self.counters.queries}: no match")
        return result

    def alias_cached_result(self, source: CardIdentity, target: CardIdentity) -> None:
        source_result = self._cache.get(_identity_key(source))
        if source_result is not None and not source_result.matched:
            self._cache[_identity_key(target)] = source_result
            if source_result.ambiguous:
                self._prime_unavailable(target)
            else:
                self._prime_no_match(target)

    def _base_params(self, identity: CardIdentity, search_text: str) -> dict[str, str]:
        params = {
            "market": "US",
            "limit": str(self.provider.config.result_limit),
            "product_type": "single",
            "search": search_text,
        }
        game = _poketrace_game(identity.language)
        if game:
            params["game"] = game
        # Deliberately no server-side card_number/set filter here. Marketplace
        # formatting (e.g. 4/102 vs 004/102, set aliases) must not hide valid
        # candidates before our normalized strict matcher sees them.
        return params

    def _request(
        self, identity: CardIdentity, search_text: str
    ) -> tuple[Optional[Mapping[str, object]], str]:
        params = self._base_params(identity, search_text)
        response, status = self._request_once(params)
        if status != REQUEST_RATE_LIMITED:
            return response, status

        retry_after = self._retry_after_seconds(response)
        # Burst 429s are seconds. A very long Retry-After indicates that a
        # diagnostic should stop rather than sleep until a daily reset.
        if retry_after is None or retry_after > 30:
            return None, REQUEST_RATE_LIMITED

        self.counters.retry_attempts += 1
        wait_seconds = max(2.25, retry_after + 0.25)
        self._progress(
            f"PokeTrace identity {self.counters.queries}: 429 retry in {wait_seconds:.2f}s"
        )
        self.provider.sleeper(wait_seconds)
        retried, retry_status = self._request_once(params)
        return retried, retry_status

    def _request_once(
        self, params: Mapping[str, str]
    ) -> tuple[Optional[object], str]:
        self.provider._respect_rate_limit()
        self.counters.search_attempts += 1
        headers = {
            "Accept": "application/json",
            "X-API-Key": self.provider.config.api_key or "",
        }
        try:
            self.provider.counters.live_calls += 1
            response = self.provider.session.get(
                "https://api.poketrace.com/v1/cards",
                headers=headers,
                params=dict(params),
                timeout=self.provider.config.timeout_seconds,
            )
        except Exception:
            self.provider.counters.request_failures += 1
            self.counters.request_failures += 1
            return None, REQUEST_ERROR

        status = getattr(response, "status_code", None)
        if status == 429:
            self.provider.counters.rate_limited += 1
            self.counters.rate_limited += 1
            return response, REQUEST_RATE_LIMITED
        if status != 200:
            self.provider.counters.request_failures += 1
            self.counters.request_failures += 1
            return response, REQUEST_ERROR
        try:
            payload = response.json()
        except Exception:
            self.provider.counters.request_failures += 1
            self.counters.request_failures += 1
            return response, REQUEST_ERROR
        return (payload if isinstance(payload, Mapping) else None), REQUEST_OK

    @staticmethod
    def _retry_after_seconds(response: object) -> Optional[float]:
        headers = getattr(response, "headers", None)
        if isinstance(headers, Mapping):
            raw = headers.get("Retry-After") or headers.get("retry-after")
            try:
                if raw is not None:
                    return max(0.0, float(str(raw).strip()))
            except ValueError:
                pass
        try:
            payload = response.json()
        except Exception:
            return None
        if isinstance(payload, Mapping):
            raw = payload.get("retryAfter")
            try:
                if raw is not None:
                    return max(0.0, float(str(raw).strip()))
            except ValueError:
                return None
        return None

    def _count_rejection(self, reason: str) -> None:
        if reason == REJECT_PRODUCT_TYPE:
            self.counters.rejected_product_type += 1
        elif reason == REJECT_CARD_NUMBER:
            self.counters.rejected_card_number += 1
        elif reason == REJECT_CARD_NAME:
            self.counters.rejected_card_name += 1
        elif reason == REJECT_SET:
            self.counters.rejected_set += 1
        elif reason == REJECT_VARIANT:
            self.counters.rejected_variant += 1
        else:
            self.counters.rejected_insufficient += 1

    def _cache_snapshot(self, identity: CardIdentity, snapshot: PokeTraceSnapshot) -> None:
        self.provider._cache[_identity_key(identity)] = snapshot
        if isinstance(self.provider, FreeTierPokeTraceProvider):
            self.provider._cache[("free",) + _identity_key(identity)] = snapshot

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
        self._cache_snapshot(original, snapshot)
        self._cache_snapshot(resolved, snapshot)
        self.counters.primed_market_snapshots += 1

    def _prime_no_match(self, identity: CardIdentity) -> None:
        self._cache_snapshot(identity, PokeTraceSnapshot(POKETRACE_NO_MATCH))

    def _prime_unavailable(self, identity: CardIdentity) -> None:
        self._cache_snapshot(identity, PokeTraceSnapshot(POKETRACE_DISABLED))

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
            "retrieval: broad search; acceptance: strict normalized local identity match",
            f"identities queried: {counters.queries}",
            f"HTTP search attempts: {counters.search_attempts}",
            f"broad fallback searches: {counters.fallback_searches}",
            f"exact matches: {counters.matches}",
            f"ambiguous: {counters.ambiguous}",
            f"no match: {counters.no_match}",
            f"cache hits: {counters.cache_hits}",
            f"request failures: {counters.request_failures}",
            f"429 responses: {counters.rate_limited}",
            f"429 retry attempts: {counters.retry_attempts}",
            f"API empty result pages: {counters.api_empty_results}",
            f"unique candidates received: {counters.candidates_received}",
            f"rejected product type: {counters.rejected_product_type}",
            f"rejected card number: {counters.rejected_card_number}",
            f"rejected card name: {counters.rejected_card_name}",
            f"rejected set: {counters.rejected_set}",
            f"rejected variant: {counters.rejected_variant}",
            f"rejected insufficient identity: {counters.rejected_insufficient}",
            f"partial-number compatible candidates: {counters.partial_number_candidates}",
            f"partial-number matches accepted: {counters.partial_number_matches}",
            f"card numbers recovered: {counters.card_numbers_recovered}",
            f"card names recovered: {counters.card_names_recovered}",
            f"sets recovered: {counters.sets_recovered}",
            f"market snapshots primed from identity response: {counters.primed_market_snapshots}",
            "extra PokeTrace request needed for a primed market match: 0",
            "persisted eBay records: 0",
        )
    )