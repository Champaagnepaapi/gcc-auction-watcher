from __future__ import annotations

import unittest
from decimal import Decimal

from v5.card_identity_catalog import HybridPokemonCardResolver
from v5.market_values.poketrace import POKETRACE_DISABLED, PokeTraceConfig
from v5.market_values.poketrace_free import FreeTierPokeTraceProvider
from v5.models import CardIdentity
from v5.poketrace_identity import PokeTraceIdentityResolver


class Response:
    def __init__(self, status_code, payload, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload


class PokeTraceSession:
    def __init__(self, responses):
        if isinstance(responses, Response):
            responses = [responses]
        elif isinstance(responses, dict):
            responses = [Response(200, responses)]
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected PokeTrace request")
        return self.responses.pop(0)


class CatalogSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params or {}, headers or {}))
        if url.endswith("/en/sets") or url.endswith("/fr/sets"):
            return Response(200, [])
        raise AssertionError(f"Pokemon TCG fallback must not be reached: {url}")


def card_payload(two=False, *, card_number="004/102", set_name="Base Set"):
    card = {
        "id": "pt-charizard-base-4",
        "name": "Charizard",
        "cardNumber": card_number,
        "set": {"name": set_name, "slug": "base-set"},
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


def identity(card_name="Charizard", set_name="Pokemon TCG Base Set", card_number="4/102"):
    return CardIdentity(
        game="Pokemon TCG",
        card_name=card_name,
        set=set_name,
        card_number=card_number,
        language="English",
        variant="Holofoil",
    )


def provider(session, sleeper=lambda _seconds: None):
    return FreeTierPokeTraceProvider(
        config=PokeTraceConfig(
            enabled=True,
            api_key="secret-never-render",
            minimum_request_interval_seconds=0,
        ),
        session=session,
        sleeper=sleeper,
    )


class PokeTraceIdentityResolverTests(unittest.TestCase):
    def test_broad_identity_and_raw_market_value_reuse_one_free_request(self):
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
        self.assertIn("Charizard", params["search"])
        self.assertIn("4/102", params["search"])
        self.assertNotIn("card_number", params)
        self.assertNotIn("set", params)
        self.assertEqual(snapshot.us_values.ungraded_value, Decimal("105"))
        self.assertIsNone(snapshot.us_values.psa10_value)
        self.assertEqual(market.counters.live_calls, 1)
        self.assertEqual(market.counters.us_matches, 1)
        self.assertEqual(resolver.counters.primed_market_snapshots, 1)

    def test_leading_zero_number_is_matched_locally_not_server_filtered(self):
        session = PokeTraceSession(card_payload(card_number="004/102"))
        resolver = PokeTraceIdentityResolver(provider(session))
        resolved = resolver.resolve_identity(identity(card_number="4/102"))
        self.assertTrue(resolved.matched)
        self.assertEqual(resolver.counters.rejected_card_number, 0)
        self.assertNotIn("card_number", session.calls[0][1]["params"])

    def test_missing_number_can_be_recovered_from_unique_name_and_set(self):
        session = PokeTraceSession(card_payload())
        resolver = PokeTraceIdentityResolver(provider(session))

        resolved = resolver.resolve_identity(identity(card_number=None, set_name="Base Set"))

        self.assertTrue(resolved.matched)
        self.assertEqual(resolved.identity.card_number, "004/102")
        self.assertEqual(resolver.counters.card_numbers_recovered, 1)

    def test_missing_name_uses_number_and_set_to_resolve(self):
        session = PokeTraceSession(card_payload())
        resolver = PokeTraceIdentityResolver(provider(session))

        resolved = resolver.resolve_identity(identity(card_name=None, set_name="Base Set"))

        self.assertTrue(resolved.matched)
        self.assertEqual(resolved.identity.card_name, "Charizard")
        self.assertEqual(resolver.counters.card_names_recovered, 1)
        self.assertIn("4/102", session.calls[0][1]["params"]["search"])

    def test_second_broader_search_can_rescue_first_empty_query(self):
        session = PokeTraceSession([
            Response(200, {"data": []}),
            Response(200, card_payload()),
        ])
        resolver = PokeTraceIdentityResolver(provider(session))

        resolved = resolver.resolve_identity(identity())

        self.assertTrue(resolved.matched)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[1][1]["params"]["search"], "Charizard")
        self.assertEqual(resolver.counters.fallback_searches, 1)
        self.assertEqual(resolver.counters.api_empty_results, 1)

    def test_rejection_reasons_are_counted_without_relaxing_acceptance(self):
        wrong_number = card_payload(card_number="5/102")["data"][0]
        wrong_set = card_payload(set_name="Jungle")["data"][0]
        session = PokeTraceSession([
            Response(200, {"data": [wrong_number, wrong_set]}),
            Response(200, {"data": []}),
        ])
        resolver = PokeTraceIdentityResolver(provider(session))

        resolved = resolver.resolve_identity(identity(set_name="Base Set"))

        self.assertFalse(resolved.matched)
        self.assertEqual(resolver.counters.rejected_card_number, 1)
        self.assertEqual(resolver.counters.rejected_set, 1)
        self.assertEqual(resolver.counters.matches, 0)

    def test_equal_best_candidates_are_ambiguous(self):
        session = PokeTraceSession(card_payload(two=True))
        resolver = PokeTraceIdentityResolver(provider(session))

        resolved = resolver.resolve_identity(identity())

        self.assertFalse(resolved.matched)
        self.assertTrue(resolved.ambiguous)
        self.assertEqual(resolver.counters.ambiguous, 1)
        self.assertEqual(len(session.calls), 1)

    def test_429_retry_after_is_retried_once_and_can_succeed(self):
        waits = []
        session = PokeTraceSession([
            Response(429, {"retryAfter": 2}, {"Retry-After": "2"}),
            Response(200, card_payload()),
        ])
        market = provider(session, sleeper=waits.append)
        resolver = PokeTraceIdentityResolver(market)

        resolved = resolver.resolve_identity(identity())

        self.assertTrue(resolved.matched)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(resolver.counters.rate_limited, 1)
        self.assertEqual(resolver.counters.retry_attempts, 1)
        self.assertTrue(any(wait >= 2.25 for wait in waits))

    def test_long_429_is_unavailable_not_false_no_match(self):
        session = PokeTraceSession(
            Response(429, {"retryAfter": 3600}, {"Retry-After": "3600"})
        )
        market = provider(session)
        resolver = PokeTraceIdentityResolver(market)
        original = identity()

        resolved = resolver.resolve_identity(original)
        snapshot = market.snapshot_for(original)

        self.assertFalse(resolved.matched)
        self.assertEqual(resolver.counters.no_match, 0)
        self.assertEqual(resolver.counters.rate_limited, 1)
        self.assertEqual(resolver.counters.retry_attempts, 0)
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
