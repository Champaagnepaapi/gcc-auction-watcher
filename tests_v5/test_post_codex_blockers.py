from __future__ import annotations

import unittest

from v5.card_identity_catalog import HybridPokemonCardResolver, MultilingualPokemonCardResolver
from v5.market_values.poketrace import PokeTraceConfig
from v5.market_values.poketrace_free import FreeTierPokeTraceProvider
from v5.models import CardIdentity
from v5.poketrace_identity import PokeTraceIdentityResolver


class _Response:
    headers = {}

    def __init__(self, status_or_payload, payload=None):
        self.status_code = 200 if payload is None else status_or_payload
        self._payload = status_or_payload if payload is None else payload

    def json(self):
        return self._payload


class _Session:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None, **kwargs):
        call = {
            "url": url,
            "params": dict(params or {}),
            "headers": dict(headers or {}),
            "timeout": timeout,
        }
        self.calls.append(call)
        return self.handler(url, call["params"], call["headers"])


def _tcgdex_handler(url, _params, _headers):
    if url.endswith("/en/sets"):
        return _Response(200, [{"id": "base1", "name": "Base Set"}])
    if url.endswith("/fr/sets"):
        return _Response(200, [])
    if url.endswith("/en/sets/base1/4"):
        return _Response(
            200,
            {
                "name": "Charizard",
                "localId": "004",
                "set": {
                    "name": "Base Set",
                    "releaseDate": "1999-01-09",
                    "cardCount": {"official": 102, "total": 102},
                },
            },
        )
    raise AssertionError(f"unexpected TCGdex request: {url}")


def _poketrace_card():
    return {
        "id": "pt-base-charizard",
        "name": "Charizard",
        "cardNumber": "004/102",
        "set": {"name": "Base Set", "slug": "base-set"},
        "productType": "single",
        "currency": "USD",
        "prices": {
            "ebay": {"NEAR_MINT": {"median7d": 100}},
            "tcgplayer": {"NEAR_MINT": {"median7d": 110}},
        },
    }


class PostCodexBlockerTests(unittest.TestCase):
    def test_tcgdex_complete_denominator_conflict_is_blocking(self):
        resolver = MultilingualPokemonCardResolver(session=_Session(_tcgdex_handler))
        identity = CardIdentity(
            game="Pokemon TCG",
            card_name="Charizard",
            set="Base Set",
            card_number="4/130",
            language="English",
        )

        result = resolver.resolve_identity(identity)

        self.assertFalse(result.matched)
        self.assertTrue(result.ambiguous)
        self.assertEqual(result.identity.card_number, "4/130")
        self.assertEqual(resolver.counters.tcgdex_denominator_conflicts, 1)

    def test_tcgdex_numerator_only_can_be_canonicalized_to_printed_number(self):
        resolver = MultilingualPokemonCardResolver(session=_Session(_tcgdex_handler))
        identity = CardIdentity(
            game="Pokemon TCG",
            card_name="Charizard",
            set="Base Set",
            card_number="4",
            language="English",
        )

        result = resolver.resolve_identity(identity)

        self.assertTrue(result.matched)
        self.assertFalse(result.ambiguous)
        self.assertEqual(result.identity.card_number, "004/102")
        self.assertEqual(
            resolver.counters.tcgdex_numerator_only_canonicalizations,
            1,
        )

    def test_hybrid_name_plus_set_can_use_poketrace_to_recover_missing_number(self):
        def pt_handler(url, params, _headers):
            self.assertTrue(url.endswith("/v1/cards"))
            self.assertEqual(params["search"], "Charizard Base Set")
            self.assertNotIn("card_number", params)
            self.assertNotIn(
                "set",
                params,
                "display set names must not be sent as PokeTrace set slugs",
            )
            return _Response({"data": [_poketrace_card()]})

        pt_session = _Session(pt_handler)
        provider = FreeTierPokeTraceProvider(
            config=PokeTraceConfig(
                enabled=True,
                api_key="unit-test-only",
                minimum_request_interval_seconds=0,
            ),
            session=pt_session,
            sleeper=lambda _seconds: None,
        )
        hybrid = HybridPokemonCardResolver(
            poketrace_identity_resolver=PokeTraceIdentityResolver(provider),
            session=_Session(_tcgdex_handler),
        )
        identity = CardIdentity(
            game="Pokemon TCG",
            card_name="Charizard",
            set="Base Set",
            card_number=None,
            language="English",
        )

        result = hybrid.resolve_identity(identity)

        self.assertTrue(result.matched)
        self.assertEqual(result.source, "POKETRACE")
        self.assertEqual(result.identity.card_number, "004/102")
        self.assertEqual(len(pt_session.calls), 1)

    def test_hybrid_exact_tcgdex_identity_avoids_poketrace_call(self):
        def unexpected_poketrace(_url, _params, _headers):
            raise AssertionError("an exact TCGdex identity must stop the chain")

        pt_session = _Session(unexpected_poketrace)
        provider = FreeTierPokeTraceProvider(
            config=PokeTraceConfig(
                enabled=True,
                api_key="unit-test-only",
                minimum_request_interval_seconds=0,
            ),
            session=pt_session,
            sleeper=lambda _seconds: None,
        )
        hybrid = HybridPokemonCardResolver(
            poketrace_identity_resolver=PokeTraceIdentityResolver(provider),
            session=_Session(_tcgdex_handler),
        )

        result = hybrid.resolve_identity(
            CardIdentity(
                game="Pokemon TCG",
                card_name="Charizard",
                set="Base Set",
                card_number="4",
                language="English",
            )
        )

        self.assertTrue(result.matched)
        self.assertEqual(result.source, "TCGDEX")
        self.assertEqual(pt_session.calls, [])
        self.assertEqual(hybrid.counters.tcgdex_only_rescues, 1)
        self.assertEqual(hybrid.counters.tcgdex_poketrace_calls_avoided, 1)

    def test_hybrid_denominator_conflict_cannot_be_overridden_by_poketrace(self):
        def unexpected_poketrace(_url, _params, _headers):
            raise AssertionError("a complete-number conflict must block fallbacks")

        pt_session = _Session(unexpected_poketrace)
        provider = FreeTierPokeTraceProvider(
            config=PokeTraceConfig(
                enabled=True,
                api_key="unit-test-only",
                minimum_request_interval_seconds=0,
            ),
            session=pt_session,
            sleeper=lambda _seconds: None,
        )
        hybrid = HybridPokemonCardResolver(
            poketrace_identity_resolver=PokeTraceIdentityResolver(provider),
            session=_Session(_tcgdex_handler),
        )

        result = hybrid.resolve_identity(
            CardIdentity(
                game="Pokemon TCG",
                card_name="Charizard",
                set="Base Set",
                card_number="4/130",
                language="English",
            )
        )

        self.assertFalse(result.matched)
        self.assertTrue(result.ambiguous)
        self.assertTrue(result.blocking)
        self.assertEqual(result.identity.card_number, "4/130")
        self.assertEqual(pt_session.calls, [])


if __name__ == "__main__":
    unittest.main()
