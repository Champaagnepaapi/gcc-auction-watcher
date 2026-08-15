from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import requests

from v5.emergency_identity_fallback import (
    EmergencyFallbackDetailedPokemonCardResolver,
    POKETRACE_EMERGENCY,
)
from v5.market_values.poketrace import PokeTraceConfig, PokeTraceProvider
from v5.models import CardIdentity
from v5.poketrace_market_only_identity import MarketOnlyPokeTraceIdentityResolver


class _Response:
    def __init__(self, status_code=200, payload=None, *, json_error=False):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error
        self.headers = {}

    def json(self):
        if self._json_error:
            raise ValueError("broken json")
        return self._payload


class _CatalogSession:
    def __init__(self, tcgdex_mode):
        self.tcgdex_mode = tcgdex_mode
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if "api.tcgdex.net" in url:
            mode = self.tcgdex_mode
            if mode == "transport":
                raise requests.Timeout("tcgdex timeout")
            if mode == "json":
                return _Response(200, json_error=True)
            if isinstance(mode, int):
                return _Response(mode, {})
            if mode == "clean_no_match":
                return _Response(200, [])
            raise AssertionError(f"unknown tcgdex mode {mode}")
        if "api.pokemontcg.io" in url:
            return _Response(200, {"data": []})
        raise AssertionError(f"unexpected catalogue URL {url}")


class _PokeTraceSession:
    def __init__(self, candidates):
        self.candidates = list(candidates)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs.get("params") or {}))
        if "api.poketrace.com/v1/cards" not in url:
            raise AssertionError(f"unexpected PokeTrace URL {url}")
        return _Response(200, {"data": self.candidates})


def _identity():
    return CardIdentity(
        game="Pokémon TCG",
        card_name="Charizard",
        set="Base Set",
        card_number="4/102",
        language="English",
    )


def _candidate(card_id="pt-charizard"):
    return {
        "id": card_id,
        "name": "Charizard",
        "cardNumber": "4/102",
        "set": {"id": "base-set", "name": "Base Set", "slug": "base-set"},
        "language": "English",
        "productType": "single",
        "market": "US",
        "currency": "USD",
        "prices": {},
    }


def _resolver(tcgdex_mode, candidates=(_candidate(),)):
    pt_session = _PokeTraceSession(candidates)
    provider = PokeTraceProvider(
        config=PokeTraceConfig(
            enabled=True,
            api_key="offline-fixture-key",
            minimum_request_interval_seconds=0,
            max_retry_after_seconds=0,
        ),
        session=pt_session,
        sleeper=lambda _seconds: None,
    )
    market_only = MarketOnlyPokeTraceIdentityResolver(provider)
    resolver = EmergencyFallbackDetailedPokemonCardResolver(
        poketrace_identity_resolver=market_only,
        session=_CatalogSession(tcgdex_mode),
    )
    return resolver, provider, pt_session


class EmergencyIdentityFallbackTests(unittest.TestCase):
    def test_transport_outage_can_use_exact_emergency_match(self):
        resolver, provider, pt_session = _resolver("transport")

        result = resolver.resolve_identity(_identity())

        self.assertTrue(result.matched)
        self.assertFalse(result.ambiguous)
        self.assertEqual(result.source, POKETRACE_EMERGENCY)
        self.assertEqual(resolver.emergency_counters.attempts, 1)
        self.assertEqual(resolver.emergency_counters.matches, 1)
        self.assertGreater(len(pt_session.calls), 0)
        self.assertEqual(provider._cache, {})
        self.assertEqual(provider._market_cache, {})
        self.assertEqual(provider._identity_primed_keys, set())
        self.assertEqual(provider._identity_primed_market_keys, set())

    def test_transient_http_statuses_allow_emergency(self):
        for status in (408, 425, 429, 500, 503):
            with self.subTest(status=status):
                resolver, _provider, pt_session = _resolver(status)
                result = resolver.resolve_identity(_identity())
                self.assertTrue(result.matched)
                self.assertEqual(result.source, POKETRACE_EMERGENCY)
                self.assertEqual(resolver.emergency_counters.attempts, 1)
                self.assertGreater(len(pt_session.calls), 0)

    def test_broken_tcgdex_json_allows_emergency(self):
        resolver, _provider, pt_session = _resolver("json")

        result = resolver.resolve_identity(_identity())

        self.assertTrue(result.matched)
        self.assertEqual(result.source, POKETRACE_EMERGENCY)
        self.assertGreaterEqual(resolver.emergency_counters.tcgdex_json_events, 1)
        self.assertGreater(len(pt_session.calls), 0)

    def test_clean_no_match_never_calls_poketrace_identity(self):
        resolver, _provider, pt_session = _resolver("clean_no_match")

        result = resolver.resolve_identity(_identity())

        self.assertFalse(result.matched)
        self.assertEqual(resolver.emergency_counters.attempts, 0)
        self.assertEqual(pt_session.calls, [])

    def test_404_and_nontransient_4xx_never_call_emergency(self):
        for status in (400, 401, 403, 404, 422):
            with self.subTest(status=status):
                resolver, _provider, pt_session = _resolver(status)
                result = resolver.resolve_identity(_identity())
                self.assertFalse(result.matched)
                self.assertEqual(resolver.emergency_counters.attempts, 0)
                self.assertEqual(pt_session.calls, [])

    def test_emergency_ambiguity_remains_fail_closed(self):
        resolver, provider, _pt_session = _resolver(
            503, (_candidate("pt-a"), _candidate("pt-b"))
        )

        result = resolver.resolve_identity(_identity())

        self.assertFalse(result.matched)
        self.assertTrue(result.ambiguous)
        self.assertEqual(result.source, POKETRACE_EMERGENCY)
        self.assertEqual(resolver.emergency_counters.ambiguous, 1)
        self.assertEqual(provider._cache, {})
        self.assertEqual(provider._market_cache, {})

    def test_zero_budget_fails_closed_without_poketrace_call(self):
        with patch.dict(
            os.environ,
            {"V5_POKETRACE_EMERGENCY_MAX_IDENTITIES_PER_RUN": "0"},
            clear=False,
        ):
            resolver, _provider, pt_session = _resolver(500)
            result = resolver.resolve_identity(_identity())

        self.assertFalse(result.matched)
        self.assertEqual(resolver.emergency_counters.attempts, 0)
        self.assertEqual(resolver.emergency_counters.budget_exhausted, 1)
        self.assertEqual(pt_session.calls, [])


if __name__ == "__main__":
    unittest.main()
