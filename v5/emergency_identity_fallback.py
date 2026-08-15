"""Emergency identity fallback for the experimental V5 live diagnostic.

Normal identity remains catalogue-first. A previously proven TCGdex macro
identity may be reused from Robot KB only when the current record experienced a
genuine TCGdex technical outage. Clean TCGdex no-match never consults that
cache. Pokemon TCG API remains the next deterministic external fallback.

PokeTrace may be used for identity only when all of the following are true:

* the current record experienced a genuine TCGdex technical outage;
* Robot KB and the normal deterministic chain (including Pokemon TCG API) did
  not resolve it;
* the identity has enough core coordinates and a PokeTrace-safe language;
* the small per-run emergency budget is not exhausted.

Emergency PokeTrace uses a separate provider instance so identity responses
cannot prime or alias the real market/pricing caches. Rate pacing and the
circuit-breaker state are propagated back to the market provider after the
emergency attempt.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Optional

from .card_identity_catalog import CatalogIdentityResult, TCGDEX_BASE
from .detailed_identity_observability import (
    DetailedDeterministicUniquenessHybridPokemonCardResolver,
    DetailedPokeTraceIdentityResolver,
    ProviderDiagnostic,
    _identity_key,
)
from .models import CardIdentity
from .robot_kb_identity_cache import (
    CACHE_AMBIGUOUS,
    CACHE_MATCHED,
    ROBOT_KB_TCGDEX_CACHE,
    RobotKBIdentityCache,
    render_robot_kb_identity_cache,
)


TCGDEX_TECHNICAL_OUTAGE = "TCGDEX_TECHNICAL_OUTAGE"
POKETRACE_EMERGENCY = "POKETRACE_EMERGENCY"
ROBOT_KB_CACHE_HIT = "ROBOT_KB_TCGDEX_CACHE_HIT"
ROBOT_KB_CACHE_AMBIGUOUS = "ROBOT_KB_TCGDEX_CACHE_AMBIGUOUS"
_TRANSIENT_HTTP = {408, 425, 429}


@dataclass(frozen=True)
class TCGdexTechnicalEvent:
    kind: str
    http_status: Optional[int] = None


class _TrackedResponse:
    def __init__(self, response, tracker: "TCGdexOutageTrackingSession") -> None:
        self._response = response
        self._tracker = tracker

    def json(self):
        try:
            return self._response.json()
        except Exception:
            self._tracker.events.append(TCGdexTechnicalEvent("json"))
            raise

    def __getattr__(self, name):
        return getattr(self._response, name)


class TCGdexOutageTrackingSession:
    """Transparent session proxy that classifies TCGdex transport/HTTP/JSON health."""

    def __init__(self, session) -> None:
        self.session = session
        self.events: list[TCGdexTechnicalEvent] = []

    def get(self, url, *args, **kwargs):
        is_tcgdex = str(url).startswith(TCGDEX_BASE)
        try:
            response = self.session.get(url, *args, **kwargs)
        except Exception:
            if is_tcgdex:
                self.events.append(TCGdexTechnicalEvent("transport"))
            raise

        if not is_tcgdex:
            return response

        status = getattr(response, "status_code", None)
        try:
            status_int = int(status) if status is not None else None
        except (TypeError, ValueError):
            status_int = None
        if status_int in _TRANSIENT_HTTP or (status_int is not None and status_int >= 500):
            self.events.append(TCGdexTechnicalEvent("transient_http", status_int))
        elif status_int not in (None, 200, 404):
            # 4xx request/auth errors are diagnostics, not outage permission.
            self.events.append(TCGdexTechnicalEvent("nontransient_http", status_int))
        return _TrackedResponse(response, self)


def _eligible_outage(events: tuple[TCGdexTechnicalEvent, ...]) -> bool:
    return any(event.kind in {"transport", "transient_http", "json"} for event in events)


def _clone_provider_for_identity(provider):
    """Clone provider runtime without copying any market or identity cache."""

    return type(provider)(
        config=provider.config,
        session=provider.session,
        monotonic=provider.monotonic,
        sleeper=provider.sleeper,
    )


def _sync_provider_runtime(source, target) -> None:
    """Propagate only quota-safety runtime, never search/cache evidence."""

    source_started = getattr(source, "_last_request_started", None)
    target_started = getattr(target, "_last_request_started", None)
    if source_started is not None and (
        target_started is None or source_started > target_started
    ):
        target._last_request_started = source_started
    if bool(getattr(source, "circuit_open", False)):
        target._circuit_open = True

    for name in (
        "live_calls",
        "request_failures",
        "rate_limited",
        "retryable_429",
        "long_429",
        "unclassified_429",
        "terminal_429_detected",
        "rate_limit_retry_attempts",
        "circuit_breaker_opened",
        "calls_avoided_after_breaker",
        "market_mismatch_rejections",
    ):
        if hasattr(source.counters, name) and hasattr(target.counters, name):
            setattr(
                target.counters,
                name,
                getattr(target.counters, name) + getattr(source.counters, name),
            )


@dataclass
class EmergencyIdentityCounters:
    technical_outage_records: int = 0
    attempts: int = 0
    matches: int = 0
    ambiguous: int = 0
    no_match: int = 0
    unavailable: int = 0
    budget_exhausted: int = 0
    skipped_without_outage: int = 0
    skipped_language_or_coordinates: int = 0
    robot_kb_hits: int = 0
    robot_kb_ambiguous: int = 0
    robot_kb_fallthrough: int = 0
    pokemon_tcg_calls_avoided_by_robot_kb: int = 0
    tcgdex_transport_events: int = 0
    tcgdex_transient_http_events: int = 0
    tcgdex_json_events: int = 0
    tcgdex_nontransient_http_events: int = 0


class EmergencyFallbackDetailedPokemonCardResolver(
    DetailedDeterministicUniquenessHybridPokemonCardResolver
):
    """Current V5 resolver plus Robot KB and tightly gated PokeTrace emergency lanes."""

    def __init__(self, *args, **kwargs) -> None:
        robot_kb_identity_cache = kwargs.pop("robot_kb_identity_cache", None)
        super().__init__(*args, **kwargs)
        tracker = TCGdexOutageTrackingSession(self.session)
        self.session = tracker
        self.tcgdex_health = tracker
        self.robot_kb_identity_cache = (
            robot_kb_identity_cache
            if robot_kb_identity_cache is not None
            else RobotKBIdentityCache.from_env()
        )
        self._active_tcgdex_event_start: Optional[int] = None
        self.emergency_counters = EmergencyIdentityCounters()
        self.emergency_max_identities = max(
            0,
            min(
                10,
                int(os.getenv("V5_POKETRACE_EMERGENCY_MAX_IDENTITIES_PER_RUN", "5")),
            ),
        )

    def _record_events(self, events: tuple[TCGdexTechnicalEvent, ...]) -> None:
        counters = self.emergency_counters
        counters.tcgdex_transport_events += sum(e.kind == "transport" for e in events)
        counters.tcgdex_transient_http_events += sum(
            e.kind == "transient_http" for e in events
        )
        counters.tcgdex_json_events += sum(e.kind == "json" for e in events)
        counters.tcgdex_nontransient_http_events += sum(
            e.kind == "nontransient_http" for e in events
        )

    def _set_robot_kb_catalog_diagnostic(
        self,
        identity: CardIdentity,
        result: CatalogIdentityResult,
        events: tuple[TCGdexTechnicalEvent, ...],
    ) -> None:
        key = _identity_key(identity)
        existing = self.catalog_diagnostic_for(identity)
        cache_reason = ROBOT_KB_CACHE_HIT if result.matched else ROBOT_KB_CACHE_AMBIGUOUS
        reasons = tuple(
            dict.fromkeys(
                existing.reason_codes + (TCGDEX_TECHNICAL_OUTAGE, cache_reason)
            )
        )
        routes = tuple(
            dict.fromkeys(existing.routes + ("robot_kb_tcgdex_cache",))
        )
        details = dict(existing.details)
        details.update(
            {
                "robot_kb_cache_attempted": True,
                "robot_kb_cache_status": "MATCHED" if result.matched else "AMBIGUOUS",
                "tcgdex_technical_events": [
                    {"kind": event.kind, "http_status": event.http_status}
                    for event in events
                ],
            }
        )
        diagnostic = replace(
            existing,
            provider=ROBOT_KB_TCGDEX_CACHE,
            status="MATCHED" if result.matched else "AMBIGUOUS",
            routes=routes,
            reason_codes=reasons,
            details=details,
        )
        self._catalog_diagnostics[key] = diagnostic
        self._catalog_diagnostics[_identity_key(result.identity)] = diagnostic

    def _set_catalog_emergency_diagnostic(
        self,
        identity: CardIdentity,
        result: CatalogIdentityResult,
        events: tuple[TCGdexTechnicalEvent, ...],
    ) -> None:
        key = _identity_key(identity)
        existing = self.catalog_diagnostic_for(identity)
        reasons = tuple(dict.fromkeys(existing.reason_codes + (TCGDEX_TECHNICAL_OUTAGE,)))
        routes = tuple(dict.fromkeys(existing.routes + ("poketrace_emergency",)))
        details = dict(existing.details)
        details.update(
            {
                "poketrace_emergency_attempted": True,
                "tcgdex_technical_events": [
                    {"kind": event.kind, "http_status": event.http_status}
                    for event in events
                ],
            }
        )
        status = (
            "MATCHED"
            if result.matched
            else ("AMBIGUOUS" if result.ambiguous else "NO_MATCH")
        )
        diagnostic = replace(
            existing,
            provider=(result.source or existing.provider),
            status=status,
            routes=routes,
            reason_codes=reasons,
            details=details,
        )
        self._catalog_diagnostics[key] = diagnostic
        self._catalog_diagnostics[_identity_key(result.identity)] = diagnostic

    def _expose_emergency_poketrace_diagnostic(
        self, identity: CardIdentity, emergency: DetailedPokeTraceIdentityResolver
    ) -> None:
        diagnostics = emergency.diagnostics_for(identity)
        if not diagnostics:
            return
        diagnostic: ProviderDiagnostic = diagnostics[0]
        details = dict(diagnostic.details)
        details["emergency_only"] = True
        self.poketrace_identity._detailed_diagnostics[_identity_key(identity)] = replace(
            diagnostic,
            provider=POKETRACE_EMERGENCY,
            details=details,
        )

    def _resolve_pokemon_tcg(self, identity: CardIdentity) -> CatalogIdentityResult:
        """On a real TCGdex outage, consult Robot KB before Pokemon TCG API."""

        event_start = self._active_tcgdex_event_start
        if event_start is not None:
            events = tuple(self.tcgdex_health.events[event_start:])
            if _eligible_outage(events):
                cached = self.robot_kb_identity_cache.lookup(identity)
                if cached.status == CACHE_MATCHED:
                    self.emergency_counters.robot_kb_hits += 1
                    self.emergency_counters.pokemon_tcg_calls_avoided_by_robot_kb += 1
                    return CatalogIdentityResult(
                        identity=cached.identity,
                        source=ROBOT_KB_TCGDEX_CACHE,
                        matched=True,
                        ambiguous=False,
                        blocking=False,
                        set_provenance=cached.set_provenance,
                    )
                if cached.status == CACHE_AMBIGUOUS:
                    self.emergency_counters.robot_kb_ambiguous += 1
                    return CatalogIdentityResult(
                        identity=identity,
                        source=ROBOT_KB_TCGDEX_CACHE,
                        matched=False,
                        ambiguous=True,
                        blocking=False,
                    )
                self.emergency_counters.robot_kb_fallthrough += 1
        return super()._resolve_pokemon_tcg(identity)

    def resolve_identity(self, identity: CardIdentity):
        event_start = len(self.tcgdex_health.events)
        previous_event_start = self._active_tcgdex_event_start
        self._active_tcgdex_event_start = event_start
        try:
            result = super().resolve_identity(identity)
        finally:
            self._active_tcgdex_event_start = previous_event_start

        events = tuple(self.tcgdex_health.events[event_start:])
        self._record_events(events)

        # Only successful exact TCGdex catalogue results are allowed to seed the
        # durable cache. A cache defect must never turn a catalogue success into
        # a live identity failure.
        if result.source == "TCGDEX" and result.matched and not result.ambiguous:
            try:
                self.robot_kb_identity_cache.store_tcgdex_result(result)
            except Exception:
                pass

        if result.source == ROBOT_KB_TCGDEX_CACHE:
            if result.matched and result.set_provenance is not None:
                self.poketrace_identity.register_set_provenance(
                    identity, result.set_provenance
                )
                self.poketrace_identity.register_set_provenance(
                    result.identity, result.set_provenance
                )
            self._set_robot_kb_catalog_diagnostic(identity, result, events)
            return result

        if result.matched or result.ambiguous or result.blocking:
            return result
        if not _eligible_outage(events):
            self.emergency_counters.skipped_without_outage += 1
            return result

        self.emergency_counters.technical_outage_records += 1
        supplied_core_fields = sum(
            bool(value)
            for value in (identity.card_name, identity.set, identity.card_number)
        )
        if supplied_core_fields < 2 or not self._poketrace_language_allowed(identity):
            self.emergency_counters.skipped_language_or_coordinates += 1
            return result
        if self.emergency_counters.attempts >= self.emergency_max_identities:
            self.emergency_counters.budget_exhausted += 1
            return result

        self.emergency_counters.attempts += 1
        market_provider = self.poketrace_identity.provider
        isolated_provider = _clone_provider_for_identity(market_provider)
        emergency = DetailedPokeTraceIdentityResolver(isolated_provider)
        try:
            emergency_result = emergency.resolve_identity(identity)
        finally:
            _sync_provider_runtime(isolated_provider, market_provider)

        self._expose_emergency_poketrace_diagnostic(identity, emergency)
        if emergency_result.matched:
            self.emergency_counters.matches += 1
            resolved = CatalogIdentityResult(
                emergency_result.identity,
                POKETRACE_EMERGENCY,
                True,
                False,
            )
            self._identity_cache[self._identity_key(identity)] = resolved
            self._set_catalog_emergency_diagnostic(identity, resolved, events)
            return resolved
        if emergency_result.ambiguous:
            self.emergency_counters.ambiguous += 1
            ambiguous = CatalogIdentityResult(
                identity,
                POKETRACE_EMERGENCY,
                False,
                True,
            )
            self._identity_cache[self._identity_key(identity)] = ambiguous
            self._set_catalog_emergency_diagnostic(identity, ambiguous, events)
            return ambiguous
        if emergency_result.provider_status:
            self.emergency_counters.unavailable += 1
        else:
            self.emergency_counters.no_match += 1
        self._set_catalog_emergency_diagnostic(identity, result, events)
        return result


def render_emergency_identity_policy(
    resolver: EmergencyFallbackDetailedPokemonCardResolver,
) -> str:
    c = resolver.emergency_counters
    return "\n".join(
        (
            "=== V5 EMERGENCY IDENTITY FALLBACK ===",
            "normal identity: TCGdex -> Robot KB on TCGdex outage -> Pokemon TCG API",
            "PokeTrace identity: emergency-only after genuine TCGdex technical outage and unresolved Robot KB/API chain",
            "eligible TCGdex failures: transport, JSON decode, HTTP 408/425/429/5xx",
            "clean TCGdex no-match consults Robot KB: NO",
            "clean TCGdex no-match triggers PokeTrace: NO",
            "other TCGdex 4xx trigger Robot KB/PokeTrace emergency: NO",
            "Robot KB cached microvariant metadata used as listing proof: NO",
            "emergency PokeTrace market-cache priming: NO (isolated provider runtime)",
            f"Robot KB exact cache hits: {c.robot_kb_hits}",
            f"Robot KB ambiguous: {c.robot_kb_ambiguous}",
            f"Robot KB fallthrough: {c.robot_kb_fallthrough}",
            (
                "Pokemon TCG calls avoided by Robot KB: "
                f"{c.pokemon_tcg_calls_avoided_by_robot_kb}"
            ),
            f"emergency identity budget/run: {resolver.emergency_max_identities}",
            f"technical-outage records: {c.technical_outage_records}",
            f"emergency attempts: {c.attempts}",
            f"emergency exact matches: {c.matches}",
            f"emergency ambiguous: {c.ambiguous}",
            f"emergency clean no-match: {c.no_match}",
            f"emergency unavailable/error: {c.unavailable}",
            f"emergency budget exhausted: {c.budget_exhausted}",
            f"skipped without eligible outage: {c.skipped_without_outage}",
            (
                "skipped language/coordinates: "
                f"{c.skipped_language_or_coordinates}"
            ),
            f"TCGdex transport events: {c.tcgdex_transport_events}",
            f"TCGdex transient HTTP events: {c.tcgdex_transient_http_events}",
            f"TCGdex JSON events: {c.tcgdex_json_events}",
            f"TCGdex non-transient HTTP events: {c.tcgdex_nontransient_http_events}",
            render_robot_kb_identity_cache(resolver.robot_kb_identity_cache),
        )
    )
