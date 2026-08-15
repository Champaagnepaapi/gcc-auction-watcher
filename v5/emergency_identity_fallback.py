"""Emergency identity fallback for the experimental V5 live diagnostic.

Normal identity remains catalogue-first. PokeTrace may be used for identity only
when all of the following are true:

* the current record experienced a genuine TCGdex technical outage;
* the normal deterministic chain (including Pokemon TCG API) did not resolve it;
* the identity has enough core coordinates and a PokeTrace-safe language;
* the small per-run emergency budget is not exhausted.

A clean TCGdex no-match never enables this path. Emergency PokeTrace uses a
separate provider instance so identity responses cannot prime or alias the real
market/pricing caches. Rate pacing and the circuit-breaker state are propagated
back to the market provider after the emergency attempt.
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


TCGDEX_TECHNICAL_OUTAGE = "TCGDEX_TECHNICAL_OUTAGE"
POKETRACE_EMERGENCY = "POKETRACE_EMERGENCY"
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
    tcgdex_transport_events: int = 0
    tcgdex_transient_http_events: int = 0
    tcgdex_json_events: int = 0
    tcgdex_nontransient_http_events: int = 0


class EmergencyFallbackDetailedPokemonCardResolver(
    DetailedDeterministicUniquenessHybridPokemonCardResolver
):
    """Current V5 resolver plus a tightly gated PokeTrace emergency lane."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        tracker = TCGdexOutageTrackingSession(self.session)
        self.session = tracker
        self.tcgdex_health = tracker
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

    def resolve_identity(self, identity: CardIdentity):
        event_start = len(self.tcgdex_health.events)
        result = super().resolve_identity(identity)
        events = tuple(self.tcgdex_health.events[event_start:])
        self._record_events(events)

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
            "normal identity: TCGdex -> Pokemon TCG API",
            "PokeTrace identity: emergency-only after genuine TCGdex technical outage",
            "eligible TCGdex failures: transport, JSON decode, HTTP 408/425/429/5xx",
            "clean TCGdex no-match triggers PokeTrace: NO",
            "other TCGdex 4xx trigger PokeTrace: NO",
            "emergency PokeTrace market-cache priming: NO (isolated provider runtime)",
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
        )
    )
