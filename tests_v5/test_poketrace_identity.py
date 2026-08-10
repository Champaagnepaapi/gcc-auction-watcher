from __future__ import annotations

import unittest
from decimal import Decimal

from v5.card_identity_catalog import HybridPokemonCardResolver
from v5.market_values.poketrace import POKETRACE_DISABLED, PokeTraceConfig
from v5.market_values.poketrace_free import FreeTierPokeTraceProvider
from v5.models import CardIdentity
from v5.poketrace_identity import PokeTraceIdentityResolver


class Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class PokeTraceSession:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response(self.status_code, self.payload)


class CatalogSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params or {}, headers or {}))
        if url.endswith("/en/sets") or url.endswith("/fr/sets"):
            return Response(200, [])
        raise AssertionError(f"Pokemon TCG fallback must not be reached: {url}")


def card_payload(two=False):
    card = {
        "id": "pt-charizard-base-4",
        "name": "Charizard",
        "cardNumber": "004/102",
        "set": {"name": "Base Set", "slug": "base-set"},
        "variant": "Holofoil",
        "rarity": "Rare Holo",
        "productType": "single",
        "market": "US",
        "currency": "USD",
        "prices": {
            "ebay": {
                "NEAR_MINT": {"median7d": 100},
                "PSA_10": {"median7d": 999},
            },
            "tcgplayer": {"NEAR_MINT": {"median7d": 110}},
        },
    }
    data = [card]
    if two:
        second = dict(card)
        second["id"] = "pt-charizard-base-4-second"
        data.append(second)
    return {"data": data}


def identity(card_name="Charizard", set_name="Pokemon TCG Base Set"):
    return CardIdentity(
        game="Pokemon TCG",
        card_name=card_name,
        set=set_name,
        card_number="4/102",
        language="English",
        variant="Holofoil",
    )


def provider(session):
    return FreeTierPokeTraceProvider(
        config=PokeTraceConfig(
            enabled=True,
            api_key="secret-never-render",
            minimum_request_interval_seconds=0,
        ),
        session=session,
    )


class PokeTraceIdentityResolverTests(unittest.TestCase):
    def test_identity_and_raw_market_value_reuse_one_free_request(self):
        session = PokeTraceSession(card_payload())
        market = provider(session)
        resolver = PokeTraceIdentityResolver(market)

        resolved = resolver.resolve_identity(identity())
        snapshot = market.snapshot_for(resolved.identity)

        self.assertTrue(resolved.matched)
        self.assertEqual(resolved.card_id, "pt-charizard-base-4")
        self.assertEqual(resolved.identity.set, "Base Set")
        self.assertEqual(len(session.calls), 1)
        params = session.calls[0][1]["params"]
        self.assertEqual(params["search"], "Charizard")
        self.assertEqual(params["card_number"], "4/102")
        self.assertNotIn("set", params)
        self.assertEqual(snapshot.us_values.ungraded_value, Decimal("105"))
        self.assertIsNone(snapshot.us_values.psa10_value)
        self.assertEqual(market.counters.live_calls, 1)
        self.assertEqual(market.counters.us_matches, 1)
        self.assertEqual(resolver.counters.primed_market_snapshots, 1)

    def test_missing_name_uses_set_slug_and_number_to_resolve(self):
        session = PokeTraceSession(card_payload())
        market = provider(session)
        resolver = PokeTraceIdentityResolver(market)

        resolved = resolver.resolve_identity(identity(card_name=None, set_name="Base Set"))

        self.assertTrue(resolved.matched)
        self.assertEqual(resolved.identity.card_name, "Charizard")
        params = session.calls[0][1]["params"]
        self.assertNotIn("search", params)
        self.assertEqual(params["set"], "base-set")
        self.assertEqual(params["card_number"], "4/102")

    def test_equal_best_candidates_are_ambiguous(self):
        session = PokeTraceSession(card_payload(two=True))
        market = provider(session)
        resolver = PokeTraceIdentityResolver(market)

        resolved = resolver.resolve_identity(identity())

        self.assertFalse(resolved.matched)
        self.assertTrue(resolved.ambiguous)
        self.assertEqual(resolver.counters.ambiguous, 1)
        self.assertEqual(len(session.calls), 1)

    def test_rate_limit_is_unavailable_not_false_no_match_and_no_second_call(self):
        session = PokeTraceSession({"data": []}, status_code=429)
        market = provider(session)
        resolver = PokeTraceIdentityResolver(market)
        original = identity()

        resolved = resolver.resolve_identity(original)
        snapshot = market.snapshot_for(original)

        self.assertFalse(resolved.matched)
        self.assertEqual(resolver.counters.no_match, 0)
        self.assertEqual(resolver.counters.rate_limited, 1)
        self.assertEqual(snapshot.status, POKETRACE_DISABLED)
        self.assertEqual(len(session.calls), 1)

    def test_hybrid_chain_uses_poketrace_before_pokemon_tcg_api(self):
        pt_session = PokeTraceSession(card_payload())
        market = provider(pt_session)
        pt_identity = PokeTraceIdentityResolver(market)
        catalog_session = CatalogSession()
        hybrid = HybridPokemonCardResolver(
            poketrace_identity_resolver=pt_identity,
            session=catalog_session,
        )

        resolved = hybrid.resolve_identity(identity(set_name="Base Set"))

        self.assertTrue(resolved.matched)
        self.assertEqual(resolved.source, "POKETRACE")
        self.assertEqual(hybrid.counters.pokemon_tcg_requests, 0)
        self.assertEqual(len(pt_session.calls), 1)
        set_calls = [url for url, _params, _headers in catalog_session.calls if url.endswith("/sets")]
        self.assertEqual(set_calls.count("https://api.tcgdex.net/v2/en/sets"), 1)
        self.assertEqual(set_calls.count("https://api.tcgdex.net/v2/fr/sets"), 1)


if __name__ == "__main__":
    unittest.main()
