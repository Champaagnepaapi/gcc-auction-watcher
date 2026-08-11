from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from typing import Mapping, Optional, Sequence, Tuple

from .market_values.poketrace import (
    POKETRACE_DISABLED,
    POKETRACE_MATCHED,
    POKETRACE_NO_MATCH,
    POKETRACE_RATE_LIMITED,
    RATE_LIMIT_LONG_NON_RETRYABLE,
    RATE_LIMIT_SHORT_RETRYABLE,
    PokeTraceProvider,
    PokeTraceSnapshot,
    _candidate_market_compatible,
    _poketrace_game,
)
from .models import CardIdentity, ProviderSearchAlias
from .poketrace_matching import (
    REJECT_CARD_NAME,
    REJECT_CARD_NUMBER,
    REJECT_INSUFFICIENT,
    REJECT_PRODUCT_TYPE,
    REJECT_SET,
    REJECT_VARIANT,
    NAME_DIFF_CASE,
    NAME_DIFF_GENDER,
    NAME_DIFF_LOCALIZATION,
    NAME_DIFF_MECHANIC_SUFFIX,
    NAME_DIFF_PUNCTUATION_ACCENTS,
    NAME_DIFF_SIGNIFICANT,
    NAME_DIFF_SIGNIFICANT_PREFIX,
    NUMBER_DIFF_ALPHANUMERIC_CASE,
    NUMBER_DIFF_CANDIDATE_NUMERATOR_ONLY,
    NUMBER_DIFF_CONTRADICTORY_AFFIX,
    NUMBER_DIFF_DENOMINATOR_CONFLICT,
    NUMBER_DIFF_DENOMINATOR_MISSING,
    NUMBER_DIFF_LEADING_ZERO,
    NUMBER_DIFF_LISTING_NUMERATOR_ONLY,
    NUMBER_DIFF_OTHER,
    NUMBER_DIFF_PREFIX_FAMILY,
    SET_DIFF_DANGEROUS_CONTAINMENT,
    SET_DIFF_EXACT_NORMALIZED,
    SET_DIFF_LANGUAGE_LOCALIZATION,
    SET_DIFF_NO_RELATION,
    SET_DIFF_PARENT_SUBSET,
    SET_DIFF_POKEMON_TCG_WRAPPER,
    SET_DIFF_PUNCTUATION_SPACING,
    SET_DIFF_SIGNIFICANT_EXTRA_TOKENS,
    CandidateMatchEvidence,
    _candidate_evidence,
    _candidate_score_and_rejection,
    _card_number_parts,
    _normalize,
    _normalize_card_name,
    _normalize_card_number,
    _partial_card_number_equivalent,
    _set_similarity,
    _variant_family,
)


REQUEST_OK = "OK"
REQUEST_ERROR = "ERROR"
REQUEST_RATE_LIMITED = "RATE_LIMITED"
REQUEST_CIRCUIT_OPEN = "CIRCUIT_OPEN"

IDENTITY_MATCHED = "MATCHED"
IDENTITY_CLEAN_NO_MATCH = "CLEAN_NO_MATCH"
IDENTITY_AMBIGUOUS = "AMBIGUOUS"
IDENTITY_ERROR = "ERROR"
IDENTITY_RATE_LIMITED = "RATE_LIMITED"
IDENTITY_BLOCKING_CONFLICT = "BLOCKING_CONFLICT"

POKETRACE_STRATEGIES = (
    "contextual_canonical",
    "contextual",
    "structured",
    "broad_name",
    "broad_number",
    "broad_set",
)

SET_DIFFERENCE_CATEGORIES = (
    SET_DIFF_EXACT_NORMALIZED,
    SET_DIFF_POKEMON_TCG_WRAPPER,
    SET_DIFF_PUNCTUATION_SPACING,
    SET_DIFF_LANGUAGE_LOCALIZATION,
    SET_DIFF_PARENT_SUBSET,
    SET_DIFF_DANGEROUS_CONTAINMENT,
    SET_DIFF_SIGNIFICANT_EXTRA_TOKENS,
    SET_DIFF_NO_RELATION,
)
NUMBER_DIFFERENCE_CATEGORIES = (
    NUMBER_DIFF_LEADING_ZERO,
    NUMBER_DIFF_DENOMINATOR_MISSING,
    NUMBER_DIFF_CANDIDATE_NUMERATOR_ONLY,
    NUMBER_DIFF_LISTING_NUMERATOR_ONLY,
    NUMBER_DIFF_DENOMINATOR_CONFLICT,
    NUMBER_DIFF_PREFIX_FAMILY,
    NUMBER_DIFF_ALPHANUMERIC_CASE,
    NUMBER_DIFF_CONTRADICTORY_AFFIX,
    NUMBER_DIFF_OTHER,
)
NAME_DIFFERENCE_CATEGORIES = (
    NAME_DIFF_CASE,
    NAME_DIFF_PUNCTUATION_ACCENTS,
    NAME_DIFF_GENDER,
    NAME_DIFF_MECHANIC_SUFFIX,
    NAME_DIFF_SIGNIFICANT_PREFIX,
    NAME_DIFF_LOCALIZATION,
    NAME_DIFF_SIGNIFICANT,
)


@dataclass
class PokeTraceStrategyCounters:
    requests: int = 0
    unique_candidates_introduced: int = 0
    near_matches_introduced: int = 0
    all_three_introduced: int = 0
    exacts_introduced: int = 0
    redundant_candidates: int = 0


@dataclass
class PokeTraceNearMatchCounters:
    set_differences: dict[str, int] = field(
        default_factory=lambda: {value: 0 for value in SET_DIFFERENCE_CATEGORIES}
    )
    number_differences: dict[str, int] = field(
        default_factory=lambda: {
            value: 0 for value in NUMBER_DIFFERENCE_CATEGORIES
        }
    )
    name_differences: dict[str, int] = field(
        default_factory=lambda: {value: 0 for value in NAME_DIFFERENCE_CATEGORIES}
    )


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
    retryable_429: int = 0
    long_429: int = 0
    unclassified_429: int = 0
    terminal_429_detected: int = 0
    retry_attempts: int = 0
    identities_skipped_after_breaker: int = 0
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
    candidates_name_matched: int = 0
    candidates_set_matched: int = 0
    candidates_card_number_matched: int = 0
    candidates_name_set_matched: int = 0
    candidates_name_number_matched: int = 0
    candidates_set_number_matched: int = 0
    candidates_all_three_matched: int = 0
    candidates_all_three_variant_compatible: int = 0
    candidates_all_three_variant_blocked: int = 0
    candidates_failing_only_one_field: int = 0
    candidates_failing_only_name: int = 0
    candidates_failing_only_set: int = 0
    candidates_failing_only_card_number: int = 0
    contextual_searches: int = 0
    canonical_contextual_searches: int = 0
    structured_searches: int = 0
    broad_name_searches: int = 0
    broad_number_searches: int = 0
    broad_set_searches: int = 0
    zero_candidate_queries: int = 0
    candidate_queries_without_exact_match: int = 0
    variant_finish_matches: int = 0
    variant_edition_matches: int = 0
    variant_promo_matches: int = 0
    variant_metadata_missing: int = 0
    variant_finish_conflicts: int = 0
    variant_edition_conflicts: int = 0
    variant_promo_conflicts: int = 0
    variant_special_finish_conflicts: int = 0
    variant_other_conflicts: int = 0
    provider_alias_identity_searches: int = 0
    alias_identity_matches: int = 0
    identity_us_queries: int = 0
    identity_us_exact_matches: int = 0
    identity_us_clean_no_matches: int = 0
    identity_eu_fallback_queries: int = 0
    identity_eu_exact_matches: int = 0
    identity_eu_clean_no_matches: int = 0
    alias_identity_searches_us: int = 0
    alias_identity_searches_eu: int = 0
    alias_identity_matches_us: int = 0
    alias_identity_matches_eu: int = 0
    eu_fallback_avoided_us_match: int = 0
    eu_fallback_suppressed_us_ambiguous: int = 0
    eu_fallback_suppressed_us_error: int = 0
    eu_fallback_suppressed_us_rate_limit: int = 0
    eu_fallback_suppressed_us_blocking_conflict: int = 0
    near_set_provider_name_exact_normalized: int = 0
    near_set_listing_name_exact_normalized: int = 0
    near_set_tcgdex_name_exact_normalized: int = 0
    near_set_provider_slug_exact_normalized: int = 0
    near_set_slug_available: int = 0
    near_set_slug_missing: int = 0
    near_set_deterministic_alias_bridge_available: int = 0
    near_set_deterministic_alias_bridge_missing: int = 0
    near_set_name_number_exact_set_unresolved: int = 0
    candidate_set_id_slug_collisions: int = 0
    near_set_tcgdex_exact_bridge_available: int = 0
    near_set_tcgdex_exact_bridge_missing: int = 0


@dataclass(frozen=True)
class PokeTraceIdentityResolution:
    identity: CardIdentity
    matched: bool = False
    ambiguous: bool = False
    card_id: Optional[str] = None
    provider_status: Optional[str] = None
    provider_market: Optional[str] = None


@dataclass(frozen=True)
class _MarketIdentityOutcome:
    market: str
    status: str
    resolution: Optional[PokeTraceIdentityResolution] = None
    card: Optional[Mapping[str, object]] = None


def _candidate_uses_partial_number(
    identity: CardIdentity, candidate: Mapping[str, object]
) -> bool:
    return _candidate_evidence(identity, candidate).number_partial


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
    )


def _candidate_key(candidate: Mapping[str, object]) -> Tuple[str, ...]:
    set_payload = candidate.get("set")
    set_name = set_payload.get("name") if isinstance(set_payload, Mapping) else None
    return (
        str(candidate.get("id") or "").strip(),
        _normalize_card_name(candidate.get("name")),
        _normalize_card_number(candidate.get("cardNumber")),
        _normalize(set_name),
        _normalize(candidate.get("variant")),
        _normalize(candidate.get("rarity")),
    )


_POKEMON_TCG_SET_PREFIX = re.compile(
    r"^\s*pok[eé]mon\s+(?:trading\s+card\s+game|tcg)\s*(?:[-:–—]\s*)?",
    flags=re.IGNORECASE,
)


def _canonical_search_set_name(value: object) -> str:
    """Remove only a known marketplace wrapper from a display set name."""

    raw = str(value or "").strip()
    stripped = _POKEMON_TCG_SET_PREFIX.sub("", raw).strip()
    return stripped or raw


def _search_strategies(
    identity: CardIdentity,
) -> Tuple[tuple[str, str, bool], ...]:
    """Return bounded retrieval strategies while keeping local acceptance strict.

    A verified PokeTrace set slug is still unavailable, so no strategy sends a
    display set name as the structured ``set=`` parameter. The contextual
    search combines independent eBay/catalog clues in the free-text query to
    improve precision server-side before broad recall fallbacks are attempted.
    """

    name = str(identity.card_name or "").strip()
    number = str(identity.card_number or "").strip()
    set_name = str(identity.set or "").strip()
    canonical_number = _normalize_card_number(number)
    canonical_set_name = _canonical_search_set_name(set_name)

    strategies: list[tuple[str, str, bool]] = []
    contextual_parts = tuple(value for value in (name, set_name, number) if value)
    if len(contextual_parts) >= 2:
        canonical_parts = tuple(
            value
            for value in (name, canonical_set_name, canonical_number)
            if value
        )
        if canonical_parts != contextual_parts:
            strategies.append(
                ("contextual_canonical", " ".join(canonical_parts), bool(number))
            )
        strategies.append(("contextual", " ".join(contextual_parts), bool(number)))

    primary_search = name or set_name or number
    if primary_search and number:
        # Card number is an official documented structured discriminator. Set
        # stays local because we do not have a verified PokeTrace set slug.
        strategies.append(("structured", primary_search, True))

    if name:
        strategies.append(("broad_name", name, False))
    if number:
        # Number-only recall is valuable when the marketplace name is noisy.
        strategies.append(("broad_number", number, False))
    if not name and set_name:
        strategies.append(("broad_set", set_name, False))

    return tuple(dict.fromkeys(strategies))


class PokeTraceIdentityResolver:
    """Contextual/structured retrieval with conservative local acceptance."""

    def __init__(self, provider: PokeTraceProvider) -> None:
        self.provider = provider
        self.counters = PokeTraceIdentityCounters()
        self.strategy_counters = {
            value: PokeTraceStrategyCounters() for value in POKETRACE_STRATEGIES
        }
        self.near_match_counters = PokeTraceNearMatchCounters()
        self._cache: dict[Tuple[str, ...], PokeTraceIdentityResolution] = {}

    def register_provider_alias(
        self, identity: CardIdentity, alias: ProviderSearchAlias
    ) -> bool:
        return self.provider.register_search_alias(identity, alias)

    def has_deterministic_alias(self, identity: CardIdentity) -> bool:
        return self.provider.has_search_alias(identity)

    def _resolution_key(self, identity: CardIdentity) -> Tuple[str, ...]:
        # The provider key includes the alias provenance. A no-match cached
        # before a deterministic alias is discovered cannot poison the later
        # alias-backed search, and variants remain isolated by _identity_key.
        return self.provider._snapshot_key(identity)

    def resolve_identity(self, identity: CardIdentity) -> PokeTraceIdentityResolution:
        if not self.provider.config.enabled or not self.provider.config.api_key:
            return PokeTraceIdentityResolution(identity)
        if sum(bool(value) for value in (identity.card_name, identity.set, identity.card_number)) < 2:
            return PokeTraceIdentityResolution(identity)

        key = self._resolution_key(identity)
        cached = self._cache.get(key)
        if cached is not None:
            self.counters.cache_hits += 1
            return cached
        if self.provider.circuit_open:
            self.counters.identities_skipped_after_breaker += 1
            self.provider._record_call_avoided_after_breaker()
            result = PokeTraceIdentityResolution(
                identity,
                provider_status=POKETRACE_RATE_LIMITED,
            )
            self._cache[key] = result
            self._prime_rate_limited(identity)
            return result

        self.counters.queries += 1
        self._progress(f"PokeTrace identity {self.counters.queries}: query")
        search_identity, provider_alias = self.provider.identity_for_search(identity)
        self.counters.identity_us_queries += 1
        us = self._resolve_market(
            identity,
            search_identity,
            provider_alias,
            "US",
        )
        if us.status == IDENTITY_MATCHED:
            self.counters.identity_us_exact_matches += 1
            if self.provider.supports_eu_market:
                self.counters.eu_fallback_avoided_us_match += 1
            return self._accept_market_match(key, identity, us, provider_alias)

        if us.status == IDENTITY_CLEAN_NO_MATCH:
            self.counters.identity_us_clean_no_matches += 1
            self.provider._prime_market_no_match(identity, "US")
            if not self.provider.supports_eu_market:
                return self._accept_overall_no_match(key, identity)

            self.counters.identity_eu_fallback_queries += 1
            eu = self._resolve_market(
                identity,
                search_identity,
                provider_alias,
                "EU",
            )
            if eu.status == IDENTITY_MATCHED:
                self.counters.identity_eu_exact_matches += 1
                return self._accept_market_match(key, identity, eu, provider_alias)
            if eu.status == IDENTITY_CLEAN_NO_MATCH:
                self.counters.identity_eu_clean_no_matches += 1
                self.provider._prime_market_no_match(identity, "EU")
                return self._accept_overall_no_match(key, identity)
            return self._accept_terminal_outcome(key, identity, eu)

        if us.status == IDENTITY_AMBIGUOUS:
            self.counters.eu_fallback_suppressed_us_ambiguous += int(
                self.provider.supports_eu_market
            )
        elif us.status == IDENTITY_RATE_LIMITED:
            self.counters.eu_fallback_suppressed_us_rate_limit += int(
                self.provider.supports_eu_market
            )
        elif us.status == IDENTITY_BLOCKING_CONFLICT:
            self.counters.eu_fallback_suppressed_us_blocking_conflict += int(
                self.provider.supports_eu_market
            )
        else:
            self.counters.eu_fallback_suppressed_us_error += int(
                self.provider.supports_eu_market
            )
        return self._accept_terminal_outcome(key, identity, us)

    def _resolve_market(
        self,
        identity: CardIdentity,
        search_identity: CardIdentity,
        provider_alias: Optional[ProviderSearchAlias],
        market: str,
    ) -> _MarketIdentityOutcome:
        seen_candidates: set[Tuple[str, ...]] = set()
        seen_set_keys: dict[str, str] = {}
        counted_set_collisions: set[Tuple[str, str, str]] = set()
        for index, (strategy, search_text, structured) in enumerate(
            _search_strategies(search_identity)
        ):
            self._count_query_strategy(strategy)
            strategy_counters = self.strategy_counters[strategy]
            if index > 0 or market == "EU":
                self.counters.fallback_searches += 1
                self._progress(
                    f"PokeTrace identity {self.counters.queries}: "
                    f"{market} fallback {strategy}"
                )
            payload, request_status = self._request(
                search_identity,
                search_text,
                use_structured_filters=structured,
                market=market,
            )
            if provider_alias is not None:
                self.counters.provider_alias_identity_searches += 1
                if market == "US":
                    self.counters.alias_identity_searches_us += 1
                else:
                    self.counters.alias_identity_searches_eu += 1
            if request_status != REQUEST_OK or payload is None:
                status = (
                    IDENTITY_RATE_LIMITED
                    if request_status in {REQUEST_RATE_LIMITED, REQUEST_CIRCUIT_OPEN}
                    else IDENTITY_ERROR
                )
                return _MarketIdentityOutcome(market, status)

            data = payload.get("data")
            raw_candidates = (
                tuple(item for item in data if isinstance(item, Mapping))
                if isinstance(data, Sequence) and not isinstance(data, (str, bytes))
                else ()
            )
            self.provider.counters.market_mismatch_rejections += sum(
                1
                for candidate in raw_candidates
                if not _candidate_market_compatible(candidate, market)
            )
            candidates = tuple(
                candidate
                for candidate in raw_candidates
                if _candidate_market_compatible(candidate, market)
            )
            if not candidates:
                self.counters.api_empty_results += 1
                self.counters.zero_candidate_queries += 1
                continue

            scored = []
            blocking_variant_conflict = False
            for candidate in candidates:
                candidate_key = _candidate_key(candidate)
                if candidate_key in seen_candidates:
                    strategy_counters.redundant_candidates += 1
                    continue
                seen_candidates.add(candidate_key)
                set_payload = candidate.get("set")
                if isinstance(set_payload, Mapping):
                    set_name = _normalize(set_payload.get("name"))
                    raw_set_key = str(
                        set_payload.get("id") or set_payload.get("slug") or ""
                    ).strip().casefold()
                    if raw_set_key and set_name:
                        previous_name = seen_set_keys.get(raw_set_key)
                        collision = (
                            raw_set_key,
                            previous_name or "",
                            set_name,
                        )
                        if (
                            previous_name
                            and previous_name != set_name
                            and collision not in counted_set_collisions
                        ):
                            self.counters.candidate_set_id_slug_collisions += 1
                            counted_set_collisions.add(collision)
                        seen_set_keys.setdefault(raw_set_key, set_name)
                self.counters.candidates_received += 1
                strategy_counters.unique_candidates_introduced += 1
                evidence = _candidate_evidence(search_identity, candidate)
                self._count_match_evidence(
                    evidence,
                    search_identity=search_identity,
                    listing_identity=identity,
                    candidate=candidate,
                    provider_alias=provider_alias,
                )
                strategy_counters.near_matches_introduced += int(
                    len(evidence.failed_core_fields) == 1
                )
                all_three = bool(
                    evidence.name_matched
                    and evidence.set_matched
                    and evidence.card_number_matched
                )
                strategy_counters.all_three_introduced += int(all_three)
                score, rejection = evidence.score, evidence.rejection
                if rejection is not None:
                    self._count_rejection(rejection, evidence)
                    blocking_variant_conflict = bool(
                        blocking_variant_conflict
                        or (all_three and rejection == REJECT_VARIANT)
                    )
                    continue
                if score is not None:
                    strategy_counters.exacts_introduced += 1
                    if evidence.number_partial:
                        self.counters.partial_number_candidates += 1
                    scored.append((score, candidate))

            if not scored:
                self.counters.candidate_queries_without_exact_match += 1
                if blocking_variant_conflict:
                    return _MarketIdentityOutcome(
                        market, IDENTITY_BLOCKING_CONFLICT
                    )
                continue

            best_score = max(score for score, _candidate in scored)
            best = tuple(candidate for score, candidate in scored if score == best_score)
            if len(best) != 1:
                self.counters.candidate_queries_without_exact_match += 1
                self.counters.ambiguous += 1
                self.provider.counters.ambiguous += 1
                return _MarketIdentityOutcome(market, IDENTITY_AMBIGUOUS)

            card = best[0]
            resolved = (
                identity
                if provider_alias is not None
                else _resolved_identity(identity, card)
            )
            result = PokeTraceIdentityResolution(
                resolved,
                matched=bool(resolved.card_name and resolved.set and resolved.card_number),
                card_id=str(card.get("id") or "").strip() or None,
                provider_status=POKETRACE_MATCHED,
                provider_market=market,
            )
            if not result.matched:
                self._count_rejection(REJECT_INSUFFICIENT)
                continue
            if _candidate_uses_partial_number(search_identity, card):
                self.counters.partial_number_matches += 1
            return _MarketIdentityOutcome(market, IDENTITY_MATCHED, result, card)

        return _MarketIdentityOutcome(market, IDENTITY_CLEAN_NO_MATCH)

    def _accept_market_match(
        self,
        key: Tuple[str, ...],
        original: CardIdentity,
        outcome: _MarketIdentityOutcome,
        provider_alias: Optional[ProviderSearchAlias],
    ) -> PokeTraceIdentityResolution:
        result = outcome.resolution
        card = outcome.card
        assert result is not None and card is not None
        resolved = result.identity
        self.counters.matches += 1
        if provider_alias is not None:
            self.counters.alias_identity_matches += 1
            if outcome.market == "US":
                self.counters.alias_identity_matches_us += 1
            else:
                self.counters.alias_identity_matches_eu += 1
        if not original.card_number and resolved.card_number:
            self.counters.card_numbers_recovered += 1
        if not original.card_name and resolved.card_name:
            self.counters.card_names_recovered += 1
        if not original.set and resolved.set:
            self.counters.sets_recovered += 1
        self._cache[key] = result
        self._cache[self._resolution_key(resolved)] = result
        self._prime_market_snapshot(
            original,
            resolved,
            card,
            market=outcome.market,
        )
        if outcome.market == "EU":
            self.provider._prime_market_no_match(resolved, "US")
        self._progress(
            f"PokeTrace identity {self.counters.queries}: {outcome.market} exact"
        )
        return result

    def _accept_overall_no_match(
        self, key: Tuple[str, ...], identity: CardIdentity
    ) -> PokeTraceIdentityResolution:
        self.counters.no_match += 1
        self.provider.counters.no_match += 1
        result = PokeTraceIdentityResolution(identity)
        self._cache[key] = result
        self._prime_no_match(identity)
        self._progress(f"PokeTrace identity {self.counters.queries}: no match")
        return result

    def _accept_terminal_outcome(
        self,
        key: Tuple[str, ...],
        identity: CardIdentity,
        outcome: _MarketIdentityOutcome,
    ) -> PokeTraceIdentityResolution:
        if outcome.status == IDENTITY_AMBIGUOUS:
            result = PokeTraceIdentityResolution(identity, ambiguous=True)
            self._prime_unavailable(identity)
        elif outcome.status == IDENTITY_RATE_LIMITED:
            result = PokeTraceIdentityResolution(
                identity,
                provider_status=POKETRACE_RATE_LIMITED,
            )
            self._prime_rate_limited(identity)
        else:
            result = PokeTraceIdentityResolution(
                identity,
                provider_status=POKETRACE_DISABLED,
            )
            self._prime_unavailable(identity)
        self._cache[key] = result
        self._progress(
            f"PokeTrace identity {self.counters.queries}: "
            f"{outcome.market} {outcome.status.casefold()}"
        )
        return result

    def alias_cached_result(self, source: CardIdentity, target: CardIdentity) -> None:
        source_result = self._cache.get(self._resolution_key(source))
        if source_result is not None and not source_result.matched:
            self._cache[self._resolution_key(target)] = source_result
            if source_result.ambiguous:
                self._prime_unavailable(target)
            elif source_result.provider_status == POKETRACE_RATE_LIMITED:
                self._prime_rate_limited(target)
            else:
                self._prime_no_match(target)

    def _base_params(
        self,
        identity: CardIdentity,
        search_text: str,
        *,
        market: str,
        use_structured_filters: bool = False,
    ) -> dict[str, str]:
        params = {
            "market": market.upper(),
            "limit": str(self.provider.config.result_limit),
            "product_type": "single",
            "search": search_text,
        }
        game = _poketrace_game(identity.language)
        if game:
            params["game"] = game
        if use_structured_filters:
            card_number = _normalize_card_number(identity.card_number)
            if card_number:
                params["card_number"] = card_number
        return params

    def _request(
        self,
        identity: CardIdentity,
        search_text: str,
        *,
        market: str,
        use_structured_filters: bool = False,
    ) -> tuple[Optional[Mapping[str, object]], str]:
        params = self._base_params(
            identity,
            search_text,
            use_structured_filters=use_structured_filters,
            market=market,
        )
        response, status = self._request_once(params)
        if status != REQUEST_RATE_LIMITED:
            return response, status

        self.counters.rate_limited += 1
        decision = self.provider._record_rate_limit(response)
        self._count_rate_limit_classification(decision.classification)
        if not decision.retryable:
            self.counters.terminal_429_detected += 1
            return None, REQUEST_RATE_LIMITED

        self.counters.retry_attempts += 1
        self.provider.counters.rate_limit_retry_attempts += 1
        wait_seconds = self.provider._rate_limit_wait_seconds(decision)
        self._progress(
            f"PokeTrace identity {self.counters.queries}: 429 retry in {wait_seconds:.2f}s"
        )
        self.provider.sleeper(wait_seconds)
        retried, retry_status = self._request_once(params)
        if retry_status == REQUEST_RATE_LIMITED:
            self.counters.rate_limited += 1
            retry_decision = self.provider._record_rate_limit(
                retried,
                retry_exhausted=True,
            )
            self._count_rate_limit_classification(retry_decision.classification)
            self.counters.terminal_429_detected += 1
        return retried, retry_status

    def _request_once(
        self, params: Mapping[str, str]
    ) -> tuple[Optional[object], str]:
        if self.provider.circuit_open:
            self.provider._record_call_avoided_after_breaker()
            return None, REQUEST_CIRCUIT_OPEN
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

    def _count_rate_limit_classification(self, classification: str) -> None:
        if classification == RATE_LIMIT_SHORT_RETRYABLE:
            self.counters.retryable_429 += 1
        elif classification == RATE_LIMIT_LONG_NON_RETRYABLE:
            self.counters.long_429 += 1
        else:
            self.counters.unclassified_429 += 1

    def _count_rejection(
        self,
        reason: str,
        evidence: Optional[CandidateMatchEvidence] = None,
    ) -> None:
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
            variant_reason = evidence.variant_reason if evidence is not None else None
            if variant_reason == "finish_conflict":
                self.counters.variant_finish_conflicts += 1
            elif variant_reason in {
                "candidate_finish_missing",
                "listing_finish_missing",
            }:
                self.counters.variant_finish_conflicts += 1
            elif variant_reason in {
                "edition_conflict",
                "candidate_edition_missing",
                "listing_edition_missing",
            }:
                self.counters.variant_edition_conflicts += 1
            elif variant_reason in {
                "promo_conflict",
                "candidate_promo_missing",
                "listing_promo_missing",
            }:
                self.counters.variant_promo_conflicts += 1
            elif variant_reason in {
                "special_finish_conflict",
                "listing_special_finish_missing",
                "candidate_special_finish_missing",
            }:
                self.counters.variant_special_finish_conflicts += 1
            else:
                self.counters.variant_other_conflicts += 1
        else:
            self.counters.rejected_insufficient += 1

    def _count_query_strategy(self, strategy: str) -> None:
        self.strategy_counters[strategy].requests += 1
        if strategy == "contextual":
            self.counters.contextual_searches += 1
        elif strategy == "contextual_canonical":
            self.counters.canonical_contextual_searches += 1
        elif strategy == "structured":
            self.counters.structured_searches += 1
        elif strategy == "broad_name":
            self.counters.broad_name_searches += 1
        elif strategy == "broad_number":
            self.counters.broad_number_searches += 1
        elif strategy == "broad_set":
            self.counters.broad_set_searches += 1

    def _count_match_evidence(
        self,
        evidence: CandidateMatchEvidence,
        *,
        search_identity: Optional[CardIdentity] = None,
        listing_identity: Optional[CardIdentity] = None,
        candidate: Optional[Mapping[str, object]] = None,
        provider_alias: Optional[ProviderSearchAlias] = None,
    ) -> None:
        counters = self.counters
        counters.candidates_name_matched += int(evidence.name_matched)
        counters.candidates_set_matched += int(evidence.set_matched)
        counters.candidates_card_number_matched += int(
            evidence.card_number_matched
        )
        counters.candidates_name_set_matched += int(
            evidence.name_matched and evidence.set_matched
        )
        counters.candidates_name_number_matched += int(
            evidence.name_matched and evidence.card_number_matched
        )
        counters.candidates_set_number_matched += int(
            evidence.set_matched and evidence.card_number_matched
        )
        all_three = bool(
            evidence.name_matched
            and evidence.set_matched
            and evidence.card_number_matched
        )
        counters.candidates_all_three_matched += int(all_three)
        counters.candidates_all_three_variant_compatible += int(
            all_three and evidence.variant_compatible
        )
        counters.candidates_all_three_variant_blocked += int(
            all_three and not evidence.variant_compatible
        )
        counters.variant_finish_matches += int(evidence.variant_finish_match)
        counters.variant_edition_matches += int(evidence.variant_edition_match)
        counters.variant_promo_matches += int(evidence.variant_promo_match)
        counters.variant_metadata_missing += int(evidence.variant_metadata_missing)
        if len(evidence.failed_core_fields) == 1:
            counters.candidates_failing_only_one_field += 1
            failed = evidence.failed_core_fields[0]
            counters.candidates_failing_only_name += int(failed == "name")
            counters.candidates_failing_only_set += int(failed == "set")
            counters.candidates_failing_only_card_number += int(
                failed == "card_number"
            )
            if failed == "name":
                self.near_match_counters.name_differences[
                    evidence.name_difference
                ] += 1
            elif failed == "set":
                self.near_match_counters.set_differences[
                    evidence.set_difference
                ] += 1
                counters.near_set_name_number_exact_set_unresolved += int(
                    evidence.name_matched and evidence.card_number_matched
                )
                set_payload = candidate.get("set") if candidate is not None else None
                set_name = (
                    set_payload.get("name")
                    if isinstance(set_payload, Mapping)
                    else None
                )
                set_slug = (
                    set_payload.get("slug")
                    if isinstance(set_payload, Mapping)
                    else None
                )
                expected_set = search_identity.set if search_identity is not None else None
                counters.near_set_provider_name_exact_normalized += int(
                    bool(expected_set)
                    and _normalize(expected_set) == _normalize(set_name)
                )
                counters.near_set_listing_name_exact_normalized += int(
                    listing_identity is not None
                    and bool(listing_identity.set)
                    and _normalize(listing_identity.set) == _normalize(set_name)
                )
                counters.near_set_tcgdex_name_exact_normalized += int(
                    provider_alias is not None
                    and _normalize(provider_alias.search_set_name)
                    == _normalize(set_name)
                )
                counters.near_set_provider_slug_exact_normalized += int(
                    bool(expected_set)
                    and bool(set_slug)
                    and _normalize(expected_set) == _normalize(set_slug)
                )
                counters.near_set_slug_available += int(bool(str(set_slug or "").strip()))
                counters.near_set_slug_missing += int(not str(set_slug or "").strip())
                alias_available = provider_alias is not None
                counters.near_set_deterministic_alias_bridge_available += int(
                    alias_available
                )
                counters.near_set_deterministic_alias_bridge_missing += int(
                    not alias_available
                )
                # In this resolver, a provider alias is emitted only by one
                # exact TCGdex English twin, so it is the deterministic bridge
                # signal.  Absence remains diagnostic and never an alias guess.
                counters.near_set_tcgdex_exact_bridge_available += int(
                    alias_available
                )
                counters.near_set_tcgdex_exact_bridge_missing += int(
                    not alias_available
                )
            elif failed == "card_number":
                category = evidence.card_number_difference
                self.near_match_counters.number_differences[category] += 1
                if category in {
                    NUMBER_DIFF_CANDIDATE_NUMERATOR_ONLY,
                    NUMBER_DIFF_LISTING_NUMERATOR_ONLY,
                }:
                    self.near_match_counters.number_differences[
                        NUMBER_DIFF_DENOMINATOR_MISSING
                    ] += 1

    def _cache_snapshot(self, identity: CardIdentity, snapshot: PokeTraceSnapshot) -> None:
        self.provider._prime_snapshot(
            self.provider._snapshot_key(identity), snapshot
        )

    def _prime_market_snapshot(
        self,
        original: CardIdentity,
        resolved: CardIdentity,
        card: Mapping[str, object],
        *,
        market: str,
    ) -> None:
        self.provider._prime_market_match(original, market, card, count_match=True)
        self.provider._prime_market_match(resolved, market, card, count_match=False)
        self.counters.primed_market_snapshots += 1

    def _prime_no_match(self, identity: CardIdentity) -> None:
        self._cache_snapshot(identity, PokeTraceSnapshot(POKETRACE_NO_MATCH))

    def _prime_unavailable(self, identity: CardIdentity) -> None:
        self._cache_snapshot(identity, PokeTraceSnapshot(POKETRACE_DISABLED))

    def _prime_rate_limited(self, identity: CardIdentity) -> None:
        self._cache_snapshot(identity, PokeTraceSnapshot(POKETRACE_RATE_LIMITED))

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
            (
                "retrieval: contextual + structured + bounded broad fallbacks; "
                "acceptance: strict shared local identity match"
            ),
            f"identities queried: {counters.queries}",
            f"HTTP search attempts: {counters.search_attempts}",
            f"fallback searches: {counters.fallback_searches}",
            f"query strategy contextual: {counters.contextual_searches}",
            (
                "query strategy canonical contextual: "
                f"{counters.canonical_contextual_searches}"
            ),
            f"query strategy structured: {counters.structured_searches}",
            f"query strategy broad-name: {counters.broad_name_searches}",
            f"query strategy broad-number: {counters.broad_number_searches}",
            f"query strategy broad-set: {counters.broad_set_searches}",
            "strategy yield (first-seen candidates per identity):",
            *(
                "strategy "
                f"{strategy.replace('_', '-')}: "
                f"requests={resolver.strategy_counters[strategy].requests}, "
                "unique="
                f"{resolver.strategy_counters[strategy].unique_candidates_introduced}, "
                "near-match="
                f"{resolver.strategy_counters[strategy].near_matches_introduced}, "
                "all-three="
                f"{resolver.strategy_counters[strategy].all_three_introduced}, "
                "exact="
                f"{resolver.strategy_counters[strategy].exacts_introduced}, "
                "redundant="
                f"{resolver.strategy_counters[strategy].redundant_candidates}"
                for strategy in POKETRACE_STRATEGIES
            ),
            f"queries returning zero candidates: {counters.zero_candidate_queries}",
            (
                "queries returning candidates but no local exact match: "
                f"{counters.candidate_queries_without_exact_match}"
            ),
            f"exact matches: {counters.matches}",
            f"identity US queries: {counters.identity_us_queries}",
            f"identity US exact matches: {counters.identity_us_exact_matches}",
            (
                "identity US clean no-match: "
                f"{counters.identity_us_clean_no_matches}"
            ),
            (
                "identity EU fallback queries: "
                f"{counters.identity_eu_fallback_queries}"
            ),
            (
                "identity EU exact matches: "
                f"{counters.identity_eu_exact_matches}"
            ),
            (
                "identity EU clean no-match: "
                f"{counters.identity_eu_clean_no_matches}"
            ),
            (
                "deterministic aliases used in identity searches: "
                f"{counters.provider_alias_identity_searches}"
            ),
            (
                "deterministic alias identity searches US: "
                f"{counters.alias_identity_searches_us}"
            ),
            (
                "deterministic alias identity searches EU: "
                f"{counters.alias_identity_searches_eu}"
            ),
            (
                "identity exacts attributable to deterministic aliases: "
                f"{counters.alias_identity_matches}"
            ),
            (
                "deterministic alias identity matches US: "
                f"{counters.alias_identity_matches_us}"
            ),
            (
                "deterministic alias identity matches EU: "
                f"{counters.alias_identity_matches_eu}"
            ),
            (
                "EU fallback avoided after US exact: "
                f"{counters.eu_fallback_avoided_us_match}"
            ),
            (
                "EU fallback suppressed after US ambiguity: "
                f"{counters.eu_fallback_suppressed_us_ambiguous}"
            ),
            (
                "EU fallback suppressed after US error: "
                f"{counters.eu_fallback_suppressed_us_error}"
            ),
            (
                "EU fallback suppressed after US rate limit: "
                f"{counters.eu_fallback_suppressed_us_rate_limit}"
            ),
            (
                "EU fallback suppressed after US blocking conflict: "
                f"{counters.eu_fallback_suppressed_us_blocking_conflict}"
            ),
            f"ambiguous: {counters.ambiguous}",
            f"no match: {counters.no_match}",
            f"cache hits: {counters.cache_hits}",
            f"request failures: {counters.request_failures}",
            f"429 responses: {counters.rate_limited}",
            f"429 short/retryable: {counters.retryable_429}",
            f"429 long/non-retryable: {counters.long_429}",
            f"429 unclassified: {counters.unclassified_429}",
            f"terminal 429 detected: {counters.terminal_429_detected}",
            f"429 retry attempts: {counters.retry_attempts}",
            (
                "circuit breaker opened: "
                f"{resolver.provider.counters.circuit_breaker_opened}"
            ),
            (
                "calls avoided after breaker: "
                f"{resolver.provider.counters.calls_avoided_after_breaker}"
            ),
            (
                "identities skipped after breaker: "
                f"{counters.identities_skipped_after_breaker}"
            ),
            f"API empty result pages: {counters.api_empty_results}",
            f"unique candidates received: {counters.candidates_received}",
            f"candidates where name matched: {counters.candidates_name_matched}",
            f"candidates where set matched: {counters.candidates_set_matched}",
            (
                "candidates where card number matched: "
                f"{counters.candidates_card_number_matched}"
            ),
            f"candidates name+set matched: {counters.candidates_name_set_matched}",
            (
                "candidates name+number matched: "
                f"{counters.candidates_name_number_matched}"
            ),
            (
                "candidates set+number matched: "
                f"{counters.candidates_set_number_matched}"
            ),
            f"candidates all three matched: {counters.candidates_all_three_matched}",
            (
                "candidates all three + variant compatible: "
                f"{counters.candidates_all_three_variant_compatible}"
            ),
            (
                "candidates all three but variant blocked: "
                f"{counters.candidates_all_three_variant_blocked}"
            ),
            (
                "candidates failing only one core field: "
                f"{counters.candidates_failing_only_one_field}"
            ),
            f"candidates failing only name: {counters.candidates_failing_only_name}",
            f"candidates failing only set: {counters.candidates_failing_only_set}",
            (
                "candidates failing only card number: "
                f"{counters.candidates_failing_only_card_number}"
            ),
            "near-match SET difference classes:",
            *(
                f"near-match SET {category}: "
                f"{resolver.near_match_counters.set_differences[category]}"
                for category in SET_DIFFERENCE_CATEGORIES
            ),
            "near-match SET deterministic bridge diagnostics (acceptance unchanged):",
            (
                "near-match SET provider name exact after safe normalization: "
                f"{counters.near_set_provider_name_exact_normalized}"
            ),
            (
                "near-match SET listing name vs provider exact normalized: "
                f"{counters.near_set_listing_name_exact_normalized}"
            ),
            (
                "near-match SET exact TCGdex twin name vs provider exact normalized: "
                f"{counters.near_set_tcgdex_name_exact_normalized}"
            ),
            (
                "near-match SET provider slug exact after safe normalization: "
                f"{counters.near_set_provider_slug_exact_normalized}"
            ),
            f"near-match SET slug available: {counters.near_set_slug_available}",
            f"near-match SET slug missing: {counters.near_set_slug_missing}",
            (
                "near-match SET deterministic alias/twin bridge available: "
                f"{counters.near_set_deterministic_alias_bridge_available}"
            ),
            (
                "near-match SET deterministic alias/twin bridge missing: "
                f"{counters.near_set_deterministic_alias_bridge_missing}"
            ),
            (
                "near-match SET exact name+number but set unresolved: "
                f"{counters.near_set_name_number_exact_set_unresolved}"
            ),
            (
                "candidate set ID/slug collisions across distinct names: "
                f"{counters.candidate_set_id_slug_collisions}"
            ),
            (
                "near-match SET exact TCGdex bridge available: "
                f"{counters.near_set_tcgdex_exact_bridge_available}"
            ),
            (
                "near-match SET exact TCGdex bridge missing: "
                f"{counters.near_set_tcgdex_exact_bridge_missing}"
            ),
            "near-match CARD NUMBER difference classes:",
            (
                "near-match CARD NUMBER denominator-missing total overlaps "
                "candidate/listing numerator-only rows"
            ),
            *(
                f"near-match CARD NUMBER {category}: "
                f"{resolver.near_match_counters.number_differences[category]}"
                for category in NUMBER_DIFFERENCE_CATEGORIES
            ),
            "near-match CARD NAME difference classes:",
            *(
                f"near-match CARD NAME {category}: "
                f"{resolver.near_match_counters.name_differences[category]}"
                for category in NAME_DIFFERENCE_CATEGORIES
            ),
            f"variant finish matches: {counters.variant_finish_matches}",
            f"variant edition matches: {counters.variant_edition_matches}",
            f"variant promo matches: {counters.variant_promo_matches}",
            f"variant metadata-missing blocks: {counters.variant_metadata_missing}",
            f"variant finish conflicts: {counters.variant_finish_conflicts}",
            f"variant edition conflicts: {counters.variant_edition_conflicts}",
            f"variant promo conflicts: {counters.variant_promo_conflicts}",
            (
                "variant special-finish conflicts: "
                f"{counters.variant_special_finish_conflicts}"
            ),
            f"variant other conflicts: {counters.variant_other_conflicts}",
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
            (
                "extra market calls avoided by identity cache: "
                f"{resolver.provider.counters.primed_market_calls_avoided}"
            ),
            "persisted eBay records: 0",
        )
    )
