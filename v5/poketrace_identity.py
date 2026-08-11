from __future__ import annotations

import os
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
from .poketrace_matching import (
    REJECT_CARD_NAME,
    REJECT_CARD_NUMBER,
    REJECT_INSUFFICIENT,
    REJECT_PRODUCT_TYPE,
    REJECT_SET,
    REJECT_VARIANT,
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


@dataclass(frozen=True)
class PokeTraceIdentityResolution:
    identity: CardIdentity
    matched: bool = False
    ambiguous: bool = False
    card_id: Optional[str] = None


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
        variant=original.variant or (str(card.get("variant") or "").strip() or None),
        rarity=original.rarity or (str(card.get("rarity") or "").strip() or None),
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
    )


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

    strategies: list[tuple[str, str, bool]] = []
    contextual_parts = tuple(value for value in (name, set_name, number) if value)
    if len(contextual_parts) >= 2:
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

        for index, (strategy, search_text, structured) in enumerate(
            _search_strategies(identity)
        ):
            self._count_query_strategy(strategy)
            if index > 0:
                self.counters.fallback_searches += 1
                self._progress(
                    f"PokeTrace identity {self.counters.queries}: fallback {strategy}"
                )
            payload, request_status = self._request(
                identity,
                search_text,
                use_structured_filters=structured,
            )
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
                self.counters.zero_candidate_queries += 1
                continue

            scored = []
            for candidate in candidates:
                candidate_key = _candidate_key(candidate)
                if candidate_key in seen_candidates:
                    continue
                seen_candidates.add(candidate_key)
                self.counters.candidates_received += 1
                evidence = _candidate_evidence(identity, candidate)
                self._count_match_evidence(evidence)
                score, rejection = evidence.score, evidence.rejection
                if rejection is not None:
                    self._count_rejection(rejection, evidence)
                    continue
                if score is not None:
                    if evidence.number_partial:
                        self.counters.partial_number_candidates += 1
                    scored.append((score, candidate))

            if not scored:
                self.counters.candidate_queries_without_exact_match += 1
                continue

            best_score = max(score for score, _candidate in scored)
            best = tuple(candidate for score, candidate in scored if score == best_score)
            if len(best) != 1:
                self.counters.candidate_queries_without_exact_match += 1
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

    def _base_params(
        self,
        identity: CardIdentity,
        search_text: str,
        *,
        use_structured_filters: bool = False,
    ) -> dict[str, str]:
        params = {
            "market": "US",
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
        use_structured_filters: bool = False,
    ) -> tuple[Optional[Mapping[str, object]], str]:
        params = self._base_params(
            identity,
            search_text,
            use_structured_filters=use_structured_filters,
        )
        response, status = self._request_once(params)
        if status != REQUEST_RATE_LIMITED:
            return response, status

        retry_after = self._retry_after_seconds(response)
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
                "edition_conflict",
                "candidate_edition_missing",
                "listing_edition_missing",
            }:
                self.counters.variant_edition_conflicts += 1
            elif variant_reason == "promo_conflict":
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
        if strategy == "contextual":
            self.counters.contextual_searches += 1
        elif strategy == "structured":
            self.counters.structured_searches += 1
        elif strategy == "broad_name":
            self.counters.broad_name_searches += 1
        elif strategy == "broad_number":
            self.counters.broad_number_searches += 1
        elif strategy == "broad_set":
            self.counters.broad_set_searches += 1

    def _count_match_evidence(self, evidence: CandidateMatchEvidence) -> None:
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

    def _cache_snapshot(self, identity: CardIdentity, snapshot: PokeTraceSnapshot) -> None:
        self.provider._prime_snapshot(_identity_key(identity), snapshot)
        if isinstance(self.provider, FreeTierPokeTraceProvider):
            self.provider._prime_snapshot(
                ("free",) + _identity_key(identity), snapshot
            )

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
            (
                "retrieval: contextual + structured + bounded broad fallbacks; "
                "acceptance: strict shared local identity match"
            ),
            f"identities queried: {counters.queries}",
            f"HTTP search attempts: {counters.search_attempts}",
            f"fallback searches: {counters.fallback_searches}",
            f"query strategy contextual: {counters.contextual_searches}",
            f"query strategy structured: {counters.structured_searches}",
            f"query strategy broad-name: {counters.broad_name_searches}",
            f"query strategy broad-number: {counters.broad_number_searches}",
            f"query strategy broad-set: {counters.broad_set_searches}",
            f"queries returning zero candidates: {counters.zero_candidate_queries}",
            (
                "queries returning candidates but no local exact match: "
                f"{counters.candidate_queries_without_exact_match}"
            ),
            f"exact matches: {counters.matches}",
            f"ambiguous: {counters.ambiguous}",
            f"no match: {counters.no_match}",
            f"cache hits: {counters.cache_hits}",
            f"request failures: {counters.request_failures}",
            f"429 responses: {counters.rate_limited}",
            f"429 retry attempts: {counters.retry_attempts}",
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
