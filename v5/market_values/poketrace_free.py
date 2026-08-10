from __future__ import annotations

from dataclasses import replace

from ..models import CardIdentity
from .poketrace import (
    POKETRACE_DISABLED,
    POKETRACE_MATCHED,
    POKETRACE_NO_MATCH,
    PokeTraceConfig,
    PokeTraceProvider,
    PokeTraceSnapshot,
    _identity_key,
    _us_market_values,
)


class FreeTierPokeTraceProvider(PokeTraceProvider):
    """PokeTrace Free test provider: US market + raw prices only.

    PokeTrace Free does not expose EU/CardMarket or graded tiers. This subclass
    deliberately performs exactly one US lookup per uncached identity so a
    diagnostic run cannot burn quota on an EU request that the plan cannot
    serve. The shared PokeTrace exact matcher and raw eBay/TCGPlayer valuation
    logic remain unchanged.
    """

    def snapshot_for(self, identity: CardIdentity) -> PokeTraceSnapshot:
        if not self.config.enabled or not self.config.api_key:
            return PokeTraceSnapshot(POKETRACE_DISABLED)

        key = ("free",) + _identity_key(identity)
        cached = self._cache.get(key)
        if cached is not None:
            self.counters.cache_hits += 1
            return cached

        us = self._search_exact(identity, "US")
        if us is None:
            result = PokeTraceSnapshot(POKETRACE_NO_MATCH)
            self.counters.no_match += 1
            self._cache[key] = result
            return result

        # Free is raw-only. Even if a fixture accidentally contains graded
        # fields, strip them before exposing values to the V5 aggregator.
        values = _us_market_values(identity, us)
        if values is not None:
            values = replace(
                values,
                source="PokeTrace Free US: eBay + TCGPlayer raw",
                grade8_generic_value=None,
                grade9_generic_value=None,
                psa10_value=None,
                notes=(
                    "Free-tier validation: US raw prices only",
                    "No EU/CardMarket request performed",
                    "No graded value accepted from the Free tier",
                ),
                limitations=(
                    "PokeTrace Free: 250 requests/day",
                    "PokeTrace Free burst: 1 request per 2 seconds",
                    "EU/CardMarket and graded tiers require Pro or higher",
                ),
            )

        result = PokeTraceSnapshot(
            POKETRACE_MATCHED if values is not None else POKETRACE_NO_MATCH,
            us_values=values,
            cardmarket=None,
        )
        if values is None:
            self.counters.no_match += 1
        self._cache[key] = result
        return result


def free_tier_config_from_env() -> PokeTraceConfig:
    """Build normal config while enforcing the documented Free burst limit."""

    config = PokeTraceConfig.from_env()
    interval = max(config.minimum_request_interval_seconds, 2.05)
    return PokeTraceConfig(
        enabled=config.enabled,
        api_key=config.api_key,
        timeout_seconds=config.timeout_seconds,
        result_limit=config.result_limit,
        minimum_request_interval_seconds=interval,
        cardmarket_discount_threshold=config.cardmarket_discount_threshold,
        falling_market_threshold=config.falling_market_threshold,
    )


def render_free_poketrace_counters(provider: FreeTierPokeTraceProvider) -> str:
    counters = provider.counters
    return "\n".join(
        (
            "=== V5 POKETRACE FREE VALIDATION ===",
            f"enabled: {str(provider.config.enabled).lower()}",
            "plan mode: FREE_TEST",
            "market requested: US only",
            "data accepted: RAW only",
            "US sources: eBay + TCGPlayer",
            "EU/CardMarket requests: 0",
            "graded values accepted: 0",
            "documented daily quota: 250 requests/day",
            "enforced minimum interval: >=2.05s",
            f"live calls: {counters.live_calls}",
            f"cache hits: {counters.cache_hits}",
            f"US exact matches: {counters.us_matches}",
            f"no match: {counters.no_match}",
            f"ambiguous: {counters.ambiguous}",
            f"request failures: {counters.request_failures}",
            f"rate limited: {counters.rate_limited}",
            "Persisted PokeTrace records: 0",
        )
    )
