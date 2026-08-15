"""Passive per-record observability overlay for the experimental V5 pipeline.

This module deliberately wraps the current V5 resolvers instead of copying their
matching or microvariant logic. Every acceptance/blocking decision is delegated
unchanged to the canonical V5 classes; this file only snapshots counters and
candidate evidence around those decisions and renders bounded diagnostics.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Mapping, Optional, Sequence, Tuple

from .card_identity_uniqueness import (
    DeterministicUniquenessHybridPokemonCardResolver,
)
from .identity_observability import sanitize_title
from .models import CardIdentity, ProviderSearchAlias
from .poketrace_identity import POKETRACE_STRATEGIES, PokeTraceIdentityResolver
from .poketrace_matching import (
    NUMBER_DIFF_DENOMINATOR_CONFLICT,
    REJECT_PRODUCT_TYPE,
    REJECT_VARIANT,
    CandidateMatchEvidence,
)
from .visual_identity import LocalVisualIdentityResolver, VisualIdentityResolution


DIAGNOSTIC_PREFIX = "[V5_IDENTITY_DIAG_V2]"
MAX_SAMPLES_PER_REASON = 3

MISSING_NAME = "MISSING_NAME"
MISSING_SET = "MISSING_SET"
MISSING_NUMBER = "MISSING_NUMBER"
DENOMINATOR_CONFLICT = "DENOMINATOR_CONFLICT"
MULTIPLE_CANONICAL_CANDIDATES = "MULTIPLE_CANONICAL_CANDIDATES"
TCGDEX_SET_NOT_FOUND = "TCGDEX_SET_NOT_FOUND"
TCGDEX_CARD_NOT_FOUND = "TCGDEX_CARD_NOT_FOUND"
TCGDEX_NUMBER_CONFLICT = "TCGDEX_NUMBER_CONFLICT"
TCGDEX_SET_CONFLICT = "TCGDEX_SET_CONFLICT"
TCGDEX_VARIANT_IMPOSSIBLE = "TCGDEX_VARIANT_IMPOSSIBLE"
TCGDEX_SEARCH_ERROR = "TCGDEX_SEARCH_ERROR"
POKEMON_TCG_SEARCH_ERROR = "POKEMON_TCG_SEARCH_ERROR"
POKETRACE_SET_MISMATCH = "POKETRACE_SET_MISMATCH"
POKETRACE_NUMBER_MISMATCH = "POKETRACE_NUMBER_MISMATCH"
POKETRACE_NAME_MISMATCH = "POKETRACE_NAME_MISMATCH"
POKETRACE_VARIANT_MISMATCH = "POKETRACE_VARIANT_MISMATCH"
POKETRACE_PRODUCT_TYPE_MISMATCH = "POKETRACE_PRODUCT_TYPE_MISMATCH"
POKETRACE_NO_EXACT_MATCH = "POKETRACE_NO_EXACT_MATCH"
POKETRACE_ZERO_CANDIDATES = "POKETRACE_ZERO_CANDIDATES"
POKETRACE_SEARCH_ERROR = "POKETRACE_SEARCH_ERROR"
POKETRACE_RATE_LIMITED = "POKETRACE_RATE_LIMITED"
VISUAL_DISABLED = "VISUAL_DISABLED"
VISUAL_NO_IMAGE = "VISUAL_NO_IMAGE"
VISUAL_NO_CANDIDATE = "VISUAL_NO_CANDIDATE"
VISUAL_NO_SCORABLE_CANDIDATE = "VISUAL_NO_SCORABLE_CANDIDATE"
VISUAL_SCORE_TOO_LOW = "VISUAL_SCORE_TOO_LOW"
VISUAL_MARGIN_TOO_SMALL = "VISUAL_MARGIN_TOO_SMALL"
VISUAL_MATCHED = "VISUAL_MATCHED"
VISUAL_SEARCH_ERROR = "VISUAL_SEARCH_ERROR"


def _as_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _counter_state(obj: object) -> dict[str, int]:
    if is_dataclass(obj):
        raw = asdict(obj)
    else:
        raw = dict(vars(obj))
    return {
        str(key): _as_int(value)
        for key, value in raw.items()
        if isinstance(value, (int, bool))
    }


def _counter_delta(before: Mapping[str, int], after: Mapping[str, int]) -> dict[str, int]:
    return {
        key: after.get(key, 0) - before.get(key, 0)
        for key in set(before) | set(after)
    }


def _identity_key(identity: CardIdentity) -> Tuple[str, ...]:
    def norm(value: object) -> str:
        return " ".join(str(value or "").strip().casefold().split())

    return (
        norm(identity.game),
        norm(identity.card_name),
        norm(identity.set),
        norm(identity.card_number),
        norm(identity.language),
        str(identity.year or ""),
        norm(identity.variant),
        norm(identity.rarity),
        norm(identity.finish),
        norm(identity.edition),
        norm(identity.illustrator),
        "|".join(norm(value) for value in identity.ambiguities),
    )


@dataclass(frozen=True)
class CandidateDiagnostic:
    provider: str
    market: Optional[str] = None
    strategy: Optional[str] = None
    candidate_id: Optional[str] = None
    name: Optional[str] = None
    set_name: Optional[str] = None
    card_number: Optional[str] = None
    language: Optional[str] = None
    variant: Optional[str] = None
    differing_fields: Tuple[str, ...] = ()
    reason_code: Optional[str] = None
    reason_detail: Optional[str] = None
    compatible: bool = False
    score: Optional[float] = None


def candidate_diagnostic(
    provider: str,
    candidate: Mapping[str, object],
    *,
    market: Optional[str] = None,
    strategy: Optional[str] = None,
    differing_fields: Sequence[str] = (),
    reason_code: Optional[str] = None,
    reason_detail: Optional[str] = None,
    compatible: bool = False,
    score: Optional[float] = None,
) -> CandidateDiagnostic:
    set_payload = candidate.get("set")
    set_name = (
        str(set_payload.get("name") or "").strip() or None
        if isinstance(set_payload, Mapping)
        else None
    )
    card_number = str(
        candidate.get("cardNumber") or candidate.get("localId") or ""
    ).strip() or None
    return CandidateDiagnostic(
        provider=provider,
        market=market,
        strategy=strategy,
        candidate_id=str(candidate.get("id") or "").strip() or None,
        name=str(candidate.get("name") or "").strip() or None,
        set_name=set_name,
        card_number=card_number,
        language=str(candidate.get("language") or "").strip() or None,
        variant=str(candidate.get("variant") or "").strip() or None,
        differing_fields=tuple(differing_fields),
        reason_code=reason_code,
        reason_detail=reason_detail,
        compatible=compatible,
        score=(round(float(score), 6) if score is not None else None),
    )


def _append_bounded_sample(
    samples: list[CandidateDiagnostic], sample: CandidateDiagnostic
) -> None:
    key = sample.reason_code or "UNCLASSIFIED"
    if sum((value.reason_code or "UNCLASSIFIED") == key for value in samples) >= MAX_SAMPLES_PER_REASON:
        return
    samples.append(sample)


@dataclass(frozen=True)
class ProviderDiagnostic:
    provider: str
    status: str = "NOT_ATTEMPTED"
    routes: Tuple[str, ...] = ()
    candidate_count: int = 0
    exact_candidate_count: int = 0
    compatible_candidate_count: int = 0
    reason_codes: Tuple[str, ...] = ()
    samples: Tuple[CandidateDiagnostic, ...] = ()
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class VisualDiagnostic:
    attempted: bool = False
    matched: bool = False
    reason_code: str = VISUAL_DISABLED
    score: Optional[float] = None
    margin: Optional[float] = None
    score_floor: Optional[float] = None
    margin_floor: Optional[float] = None
    top_candidates: Tuple[str, ...] = ()
    details: Mapping[str, object] = field(default_factory=dict)


class DetailedPokeTraceIdentityResolver(PokeTraceIdentityResolver):
    """PokeTrace resolver with passive, bounded per-identity evidence capture."""

    def __init__(self, provider) -> None:
        super().__init__(provider)
        self._detailed_diagnostics: dict[Tuple[str, ...], ProviderDiagnostic] = {}
        self._active_detail_key: Optional[Tuple[str, ...]] = None
        self._active_market: Optional[str] = None
        self._active_strategy: Optional[str] = None
        self._active_samples: list[CandidateDiagnostic] = []

    def diagnostics_for(self, identity: CardIdentity) -> Tuple[ProviderDiagnostic, ...]:
        diagnostic = self._detailed_diagnostics.get(_identity_key(identity))
        return (diagnostic,) if diagnostic is not None else ()

    def _resolve_market(
        self,
        identity: CardIdentity,
        search_identity: CardIdentity,
        provider_alias: Optional[ProviderSearchAlias],
        market: str,
    ):
        previous_market = self._active_market
        self._active_market = market
        try:
            return super()._resolve_market(
                identity,
                search_identity,
                provider_alias,
                market,
            )
        finally:
            self._active_market = previous_market

    def _count_query_strategy(self, strategy: str) -> None:
        self._active_strategy = strategy
        super()._count_query_strategy(strategy)

    @staticmethod
    def _reason_for_evidence(evidence: CandidateMatchEvidence) -> Optional[str]:
        if evidence.rejection == REJECT_PRODUCT_TYPE:
            return POKETRACE_PRODUCT_TYPE_MISMATCH
        if evidence.rejection == REJECT_VARIANT:
            return POKETRACE_VARIANT_MISMATCH
        if evidence.failed_core_fields == ("name",):
            return POKETRACE_NAME_MISMATCH
        if evidence.failed_core_fields == ("set",):
            return POKETRACE_SET_MISMATCH
        if evidence.failed_core_fields == ("card_number",):
            if evidence.card_number_difference == NUMBER_DIFF_DENOMINATOR_CONFLICT:
                return DENOMINATOR_CONFLICT
            return POKETRACE_NUMBER_MISMATCH
        if evidence.rejection is not None or evidence.failed_core_fields:
            return POKETRACE_NO_EXACT_MATCH
        return None

    def _count_match_evidence(
        self,
        evidence: CandidateMatchEvidence,
        *,
        search_identity: Optional[CardIdentity] = None,
        listing_identity: Optional[CardIdentity] = None,
        candidate: Optional[Mapping[str, object]] = None,
        provider_alias: Optional[ProviderSearchAlias] = None,
    ) -> None:
        super()._count_match_evidence(
            evidence,
            search_identity=search_identity,
            listing_identity=listing_identity,
            candidate=candidate,
            provider_alias=provider_alias,
        )
        if self._active_detail_key is None or candidate is None:
            return
        reason = self._reason_for_evidence(evidence)
        if reason is None and not (
            evidence.name_matched
            and evidence.set_matched
            and evidence.card_number_matched
        ):
            return
        detail = (
            evidence.variant_reason
            if evidence.rejection == REJECT_VARIANT
            else evidence.name_difference
            if evidence.failed_core_fields == ("name",)
            else evidence.set_difference
            if evidence.failed_core_fields == ("set",)
            else evidence.card_number_difference
            if evidence.failed_core_fields == ("card_number",)
            else evidence.rejection
        )
        _append_bounded_sample(
            self._active_samples,
            candidate_diagnostic(
                "POKETRACE",
                candidate,
                market=self._active_market,
                strategy=self._active_strategy,
                differing_fields=evidence.failed_core_fields,
                reason_code=reason,
                reason_detail=detail,
                compatible=bool(evidence.rejection is None),
                score=evidence.score,
            ),
        )

    def resolve_identity(self, identity: CardIdentity):
        key = _identity_key(identity)
        before = _counter_state(self.counters)
        before_strategies = {
            strategy: _counter_state(self.strategy_counters[strategy])
            for strategy in POKETRACE_STRATEGIES
        }
        before_near_set = dict(self.near_match_counters.set_differences)
        before_near_number = dict(self.near_match_counters.number_differences)
        before_near_name = dict(self.near_match_counters.name_differences)
        previous_key = self._active_detail_key
        previous_samples = self._active_samples
        self._active_detail_key = key
        self._active_samples = []
        try:
            result = super().resolve_identity(identity)
            samples = tuple(self._active_samples)
        finally:
            self._active_detail_key = previous_key
            self._active_samples = previous_samples

        after = _counter_state(self.counters)
        delta = _counter_delta(before, after)
        strategy_delta = {
            strategy: _counter_delta(
                before_strategies[strategy],
                _counter_state(self.strategy_counters[strategy]),
            )
            for strategy in POKETRACE_STRATEGIES
        }
        routes = tuple(
            strategy
            for strategy in POKETRACE_STRATEGIES
            if strategy_delta[strategy].get("requests", 0) > 0
        )
        reason_codes: list[str] = []
        if delta.get("rate_limited", 0) or "RATE_LIMIT" in str(result.provider_status or "").upper():
            reason_codes.append(POKETRACE_RATE_LIMITED)
        if delta.get("request_failures", 0):
            reason_codes.append(POKETRACE_SEARCH_ERROR)
        if delta.get("rejected_product_type", 0):
            reason_codes.append(POKETRACE_PRODUCT_TYPE_MISMATCH)
        if delta.get("rejected_card_name", 0):
            reason_codes.append(POKETRACE_NAME_MISMATCH)
        if delta.get("rejected_set", 0):
            reason_codes.append(POKETRACE_SET_MISMATCH)
        if delta.get("rejected_card_number", 0):
            reason_codes.append(POKETRACE_NUMBER_MISMATCH)
        if delta.get("rejected_variant", 0):
            reason_codes.append(POKETRACE_VARIANT_MISMATCH)
        if delta.get("candidate_set_id_slug_collisions", 0) or result.ambiguous:
            reason_codes.append(MULTIPLE_CANONICAL_CANDIDATES)
        if delta.get("zero_candidate_queries", 0):
            reason_codes.append(POKETRACE_ZERO_CANDIDATES)
        if not result.matched and delta.get("candidates_received", 0) and not result.ambiguous:
            reason_codes.append(POKETRACE_NO_EXACT_MATCH)

        if result.matched:
            status = "MATCHED"
        elif result.ambiguous:
            status = "AMBIGUOUS"
        elif delta.get("cache_hits", 0) and not delta.get("queries", 0):
            status = "CACHED"
        elif POKETRACE_RATE_LIMITED in reason_codes:
            status = "RATE_LIMITED"
        elif delta.get("request_failures", 0):
            status = "ERROR"
        elif delta.get("no_match", 0) or delta.get("queries", 0):
            status = "NO_MATCH"
        else:
            status = "NOT_ATTEMPTED_OR_INELIGIBLE"

        near_breakdown = {
            "set": {
                name: value - before_near_set.get(name, 0)
                for name, value in self.near_match_counters.set_differences.items()
                if value - before_near_set.get(name, 0) > 0
            },
            "number": {
                name: value - before_near_number.get(name, 0)
                for name, value in self.near_match_counters.number_differences.items()
                if value - before_near_number.get(name, 0) > 0
            },
            "name": {
                name: value - before_near_name.get(name, 0)
                for name, value in self.near_match_counters.name_differences.items()
                if value - before_near_name.get(name, 0) > 0
            },
        }
        diagnostic = ProviderDiagnostic(
            provider="POKETRACE",
            status=status,
            routes=routes,
            candidate_count=max(0, delta.get("candidates_received", 0)),
            exact_candidate_count=sum(
                max(0, values.get("exacts_introduced", 0))
                for values in strategy_delta.values()
            ),
            compatible_candidate_count=max(
                0, delta.get("candidates_all_three_variant_compatible", 0)
            ),
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            samples=samples,
            details={
                "us_queries": max(0, delta.get("identity_us_queries", 0)),
                "eu_fallback_queries": max(0, delta.get("identity_eu_fallback_queries", 0)),
                "fallback_searches": max(0, delta.get("fallback_searches", 0)),
                "near_match_breakdown": near_breakdown,
            },
        )
        self._detailed_diagnostics[key] = diagnostic
        self._detailed_diagnostics[_identity_key(result.identity)] = diagnostic
        return result


class DetailedDeterministicUniquenessHybridPokemonCardResolver(
    DeterministicUniquenessHybridPokemonCardResolver
):
    """Current uniqueness resolver plus passive TCGdex/Pokémon-TCG diagnostics."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._catalog_diagnostics: dict[Tuple[str, ...], ProviderDiagnostic] = {}

    def catalog_diagnostic_for(self, identity: CardIdentity) -> ProviderDiagnostic:
        return self._catalog_diagnostics.get(
            _identity_key(identity), ProviderDiagnostic("TCGDEX")
        )

    def resolve_identity(self, identity: CardIdentity):
        key = _identity_key(identity)
        before = _counter_state(self.counters)
        before_uniqueness = _counter_state(self.uniqueness_counters)
        before_card_keys = set(self._card_cache)
        result = super().resolve_identity(identity)
        delta = _counter_delta(before, _counter_state(self.counters))
        uniqueness_delta = _counter_delta(
            before_uniqueness, _counter_state(self.uniqueness_counters)
        )

        new_card_keys = tuple(key_ for key_ in self._card_cache if key_ not in before_card_keys)
        cards = tuple(
            self._card_cache[key_]
            for key_ in new_card_keys
            if isinstance(self._card_cache[key_], Mapping)
        )
        routes = [key_[3] for key_ in new_card_keys]
        if uniqueness_delta.get("name_number_attempts", 0):
            routes.insert(0, "unique_name_complete_number")
        if uniqueness_delta.get("set_name_attempts", 0):
            routes.insert(0, "unique_set_exact_name")
        if delta.get("tcgdex_requests", 0) and not routes:
            routes.append("tcgdex_cached_or_catalog")
        if delta.get("pokemon_tcg_requests", 0):
            routes.append("pokemon_tcg_fallback")

        reason_codes: list[str] = []
        if delta.get("tcgdex_denominator_conflicts", 0):
            reason_codes.append(DENOMINATOR_CONFLICT)
        if delta.get("tcgdex_ambiguous_set_aliases", 0) or result.ambiguous:
            reason_codes.append(MULTIPLE_CANONICAL_CANDIDATES)
        if delta.get("tcgdex_no_match_set", 0):
            reason_codes.append(TCGDEX_SET_NOT_FOUND)
        if delta.get("tcgdex_no_match_card", 0):
            reason_codes.append(TCGDEX_CARD_NOT_FOUND)
        if delta.get("tcgdex_no_match_number_conflict", 0) and DENOMINATOR_CONFLICT not in reason_codes:
            reason_codes.append(TCGDEX_NUMBER_CONFLICT)
        if delta.get("tcgdex_no_match_set_conflict", 0):
            reason_codes.append(TCGDEX_SET_CONFLICT)
        if delta.get("tcgdex_variant_impossible", 0) or uniqueness_delta.get("variant_conflicts", 0):
            reason_codes.append(TCGDEX_VARIANT_IMPOSSIBLE)
        if (
            delta.get("tcgdex_transport_failures", 0)
            or delta.get("tcgdex_http_failures", 0)
            or delta.get("tcgdex_json_failures", 0)
        ):
            reason_codes.append(TCGDEX_SEARCH_ERROR)
        if (
            delta.get("pokemon_tcg_transport_failures", 0)
            or delta.get("pokemon_tcg_http_failures", 0)
            or delta.get("pokemon_tcg_json_failures", 0)
        ):
            reason_codes.append(POKEMON_TCG_SEARCH_ERROR)
        if not identity.card_name:
            reason_codes.append(MISSING_NAME)
        if not identity.set:
            reason_codes.append(MISSING_SET)
        if not identity.card_number:
            reason_codes.append(MISSING_NUMBER)

        if result.matched:
            status = "MATCHED"
        elif result.ambiguous:
            status = "AMBIGUOUS"
        elif result.blocking:
            status = "BLOCKING"
        elif delta.get("cache_hits", 0) and not (
            delta.get("tcgdex_requests", 0) or delta.get("pokemon_tcg_requests", 0)
        ):
            status = "CACHED"
        else:
            status = "NO_MATCH"

        sample_reason = reason_codes[0] if reason_codes else None
        samples = tuple(
            candidate_diagnostic(
                "TCGDEX",
                card,
                reason_code=sample_reason,
                reason_detail="observed during the unchanged catalogue decision",
                compatible=bool(result.matched),
            )
            for card in cards[:MAX_SAMPLES_PER_REASON]
        )
        diagnostic = ProviderDiagnostic(
            provider=(result.source or "TCGDEX"),
            status=status,
            routes=tuple(dict.fromkeys(routes)),
            candidate_count=len(cards),
            exact_candidate_count=int(result.matched),
            compatible_candidate_count=int(result.matched),
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            samples=samples,
            details={
                "tcgdex_requests": max(0, delta.get("tcgdex_requests", 0)),
                "pokemon_tcg_requests": max(0, delta.get("pokemon_tcg_requests", 0)),
                "uniqueness_attempts": max(0, uniqueness_delta.get("attempts", 0)),
                "uniqueness_name_number_hits": max(0, uniqueness_delta.get("name_number_hits", 0)),
                "uniqueness_set_name_hits": max(0, uniqueness_delta.get("set_name_hits", 0)),
            },
        )
        self._catalog_diagnostics[key] = diagnostic
        self._catalog_diagnostics[_identity_key(result.identity)] = diagnostic
        return result


class DetailedLocalVisualIdentityResolver(LocalVisualIdentityResolver):
    """Current visual resolver plus passive reason/threshold snapshots."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._visual_diagnostics: dict[Tuple[str, ...], VisualDiagnostic] = {}

    def diagnostic_for(self, identity: CardIdentity) -> VisualDiagnostic:
        return self._visual_diagnostics.get(_identity_key(identity), VisualDiagnostic())

    def resolve_identity(self, identity: CardIdentity, image_urls, **kwargs):
        before = _counter_state(self.counters)
        result: VisualIdentityResolution = super().resolve_identity(
            identity, image_urls, **kwargs
        )
        delta = _counter_delta(before, _counter_state(self.counters))
        attempted = bool(delta.get("attempted", 0) or result.matched or result.score or result.margin)

        if result.matched:
            reason = VISUAL_MATCHED
        elif not self.enabled or not self.provider.config.enabled or not self.provider.config.api_key:
            reason = VISUAL_DISABLED
        elif delta.get("no_ebay_image", 0):
            reason = VISUAL_NO_IMAGE
        elif delta.get("api_unavailable", 0) or delta.get("visual_searches_skipped_after_breaker", 0):
            reason = VISUAL_SEARCH_ERROR
        elif delta.get("no_candidates", 0):
            reason = VISUAL_NO_CANDIDATE
        elif delta.get("close_second", 0):
            reason = VISUAL_MARGIN_TOO_SMALL
        elif delta.get("low_confidence", 0):
            reason = VISUAL_SCORE_TOO_LOW if result.score else VISUAL_NO_SCORABLE_CANDIDATE
        else:
            reason = VISUAL_NO_CANDIDATE if attempted else VISUAL_DISABLED

        visual = VisualDiagnostic(
            attempted=attempted,
            matched=bool(result.matched),
            reason_code=reason,
            score=(round(float(result.score), 6) if result.score else None),
            margin=(round(float(result.margin), 6) if result.margin else None),
            score_floor=self.minimum_score,
            margin_floor=self.minimum_margin,
            top_candidates=tuple(result.top_candidates),
            details={
                "override_number_score_floor": self.override_number_minimum_score,
                "override_number_margin_floor": self.override_number_minimum_margin,
                "microvariant_gate_blocked_before_market": max(
                    0, delta.get("microvariant_gate_blocked_before_market", 0)
                ),
            },
        )
        self._visual_diagnostics[_identity_key(identity)] = visual
        self._visual_diagnostics[_identity_key(result.identity)] = visual
        return result


def _identity_from_simple_diagnostic(simple) -> CardIdentity:
    return CardIdentity(
        game="Pokémon TCG",
        card_name=simple.card_name,
        set=simple.set_name,
        card_number=simple.card_number,
        language=simple.language,
    )


def detailed_record_payload(simple, resolver, visual_resolver) -> Mapping[str, object]:
    """Convert the current V5 unresolved diagnostic into richer passive JSON."""

    identity = _identity_from_simple_diagnostic(simple)
    catalog = (
        resolver.catalog_diagnostic_for(identity)
        if hasattr(resolver, "catalog_diagnostic_for")
        else ProviderDiagnostic("TCGDEX")
    )
    poketrace = (
        resolver.poketrace_identity.diagnostics_for(identity)
        if hasattr(resolver, "poketrace_identity")
        and hasattr(resolver.poketrace_identity, "diagnostics_for")
        else ()
    )
    visual = (
        visual_resolver.diagnostic_for(identity)
        if visual_resolver is not None and hasattr(visual_resolver, "diagnostic_for")
        else VisualDiagnostic()
    )
    variant = asdict(simple.variant_diag) if simple.variant_diag is not None else None
    return {
        "schema_version": 2,
        "record": simple.record,
        "item_id": simple.item_id,
        "title": sanitize_title(simple.title),
        "final_status": simple.final_status,
        "final_reason_code": simple.reason_code,
        "explanation": simple.explanation,
        "identity": {
            "name": simple.card_name,
            "set": simple.set_name,
            "number": simple.card_number,
            "language": simple.language,
        },
        "coordinates": asdict(simple.coordinates),
        "ambiguity_fields": list(simple.ambiguity_fields),
        "catalog": asdict(catalog),
        "poketrace": [asdict(value) for value in poketrace],
        "visual": asdict(visual),
        "variant": variant,
    }


def render_detailed_record(simple, resolver, visual_resolver) -> str:
    return DIAGNOSTIC_PREFIX + " " + json.dumps(
        detailed_record_payload(simple, resolver, visual_resolver),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
