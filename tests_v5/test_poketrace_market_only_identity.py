from __future__ import annotations

import unittest
from types import SimpleNamespace

from v5.detailed_identity_observability import (
    DetailedDeterministicUniquenessHybridPokemonCardResolver,
    VISUAL_DISABLED,
)
from v5.models import CardIdentity
from v5.poketrace_market_only_identity import (
    MarketOnlyPokeTraceIdentityResolver,
    MarketOnlyPokeTraceVisualIdentityResolver,
    POKETRACE_IDENTITY_MARKET_ONLY,
    POKETRACE_MARKET_ONLY_STATUS,
)


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _CatalogSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params or {}))
        if url.endswith("/en/sets") or url.endswith("/fr/sets"):
            return _Response(200, [])
        if url.endswith("/v2/cards"):
            return _Response(
                200,
                {
                    "data": [
                        {
                            "id": "base1-4",
                            "name": "Charizard",
                            "number": "4",
                            "set": {
                                "name": "Base Set",
                                "releaseDate": "1999/01/09",
                            },
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected catalogue request: {url}")


class _ExplodingMarketProvider:
    """Provider fixture: registration is allowed, identity network is not."""

    def __init__(self):
        self.config = SimpleNamespace(enabled=True, api_key="fixture-not-a-secret")
        self.aliases = []
        self.provenance = []

    def register_search_alias(self, identity, alias):
        self.aliases.append((identity, alias))
        return True

    def register_set_provenance(self, identity, provenance):
        self.provenance.append((identity, provenance))
        return True

    def has_search_alias(self, _identity):
        return False

    def identity_for_search(self, _identity):
        raise AssertionError("PokeTrace identity network/search path must stay unused")


class PokeTraceMarketOnlyIdentityTests(unittest.TestCase):
    @staticmethod
    def _identity():
        return CardIdentity(
            game="Pokémon TCG",
            card_name="Charizard",
            set="Base Set",
            card_number="4/102",
            language="English",
        )

    def test_identity_resolver_is_explicit_noop_without_touching_market_provider(self):
        provider = _ExplodingMarketProvider()
        resolver = MarketOnlyPokeTraceIdentityResolver(provider)
        identity = self._identity()

        result = resolver.resolve_identity(identity)

        self.assertFalse(result.matched)
        self.assertFalse(result.ambiguous)
        self.assertEqual(result.identity, identity)
        self.assertEqual(result.provider_status, POKETRACE_MARKET_ONLY_STATUS)
        self.assertEqual(resolver.identity_disabled_skips, 1)
        self.assertEqual(resolver.counters.queries, 0)
        self.assertEqual(resolver.counters.search_attempts, 0)
        self.assertTrue(provider.config.enabled)
        diagnostic = resolver.diagnostics_for(identity)[0]
        self.assertEqual(diagnostic.status, POKETRACE_MARKET_ONLY_STATUS)
        self.assertIn(POKETRACE_IDENTITY_MARKET_ONLY, diagnostic.reason_codes)
        self.assertEqual(diagnostic.details["identity_requests_sent"], 0)

    def test_catalog_chain_skips_poketrace_identity_then_uses_pokemon_tcg_fallback(self):
        provider = _ExplodingMarketProvider()
        poketrace_identity = MarketOnlyPokeTraceIdentityResolver(provider)
        session = _CatalogSession()
        resolver = DetailedDeterministicUniquenessHybridPokemonCardResolver(
            poketrace_identity_resolver=poketrace_identity,
            session=session,
        )

        result = resolver.resolve_identity(self._identity())

        self.assertTrue(result.matched)
        self.assertEqual(result.source, "POKEMON_TCG")
        self.assertEqual(result.identity.card_name, "Charizard")
        self.assertEqual(poketrace_identity.identity_disabled_skips, 1)
        self.assertEqual(poketrace_identity.counters.search_attempts, 0)
        self.assertEqual(resolver.counters.pokemon_tcg_hits, 1)
        self.assertTrue(any(url.endswith("/v2/cards") for url, _params in session.calls))

    def test_poketrace_backed_visual_identity_is_forced_off(self):
        provider = _ExplodingMarketProvider()
        poketrace_identity = MarketOnlyPokeTraceIdentityResolver(provider)
        visual = MarketOnlyPokeTraceVisualIdentityResolver(
            poketrace_identity,
            ebay_image_fetcher=lambda _url: b"unused",
            enabled=True,
        )
        identity = self._identity()

        result = visual.resolve_identity(
            identity,
            ("https://example.invalid/card.jpg",),
            marketplace_id="EBAY_US",
        )

        self.assertFalse(visual.enabled)
        self.assertFalse(result.matched)
        self.assertEqual(visual.counters.api_searches, 0)
        self.assertEqual(visual.diagnostic_for(identity).reason_code, VISUAL_DISABLED)


if __name__ == "__main__":
    unittest.main()
