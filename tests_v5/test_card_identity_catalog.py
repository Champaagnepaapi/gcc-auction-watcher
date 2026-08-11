from __future__ import annotations

import unittest

from v5.card_identity_catalog import MultilingualPokemonCardResolver
from v5.models import CardIdentity


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _Session:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params or {}, headers or {}))
        return self.handler(url, params or {}, headers or {})


class MultilingualPokemonCardResolverTests(unittest.TestCase):
    def test_tcgdex_propagates_canonical_name_set_and_printed_number(self):
        def handler(url, _params, _headers):
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
            raise AssertionError(f"unexpected request: {url}")

        resolver = MultilingualPokemonCardResolver(session=_Session(handler))
        result = resolver.resolve_identity(
            CardIdentity(
                game="Pokémon TCG",
                card_name="Charizard Card",
                set="Pokemon TCG Base Set",
                card_number="4",
                language="English",
            )
        )

        self.assertTrue(result.matched)
        self.assertEqual(result.identity.card_name, "Charizard")
        self.assertEqual(result.identity.set, "Base Set")
        self.assertEqual(result.identity.card_number, "004/102")
        self.assertEqual(resolver.counters.canonical_name_changes, 1)
        self.assertEqual(resolver.counters.canonical_set_changes, 1)
        self.assertEqual(resolver.counters.canonical_card_number_changes, 1)

    def test_french_identity_is_localized_by_tcgdex_without_losing_language(self):
        def handler(url, params, _headers):
            if url.endswith("/fr/sets"):
                return _Response(200, [])
            if url.endswith("/en/sets"):
                return _Response(200, [{"id": "base3", "name": "Fossil"}])
            if url.endswith("/fr/sets/base3/46"):
                return _Response(
                    200,
                    {
                        "name": "Abo",
                        "localId": "46",
                        "set": {"name": "Fossile", "releaseDate": "1999-10-10"},
                    },
                )
            raise AssertionError(f"unexpected request: {url}")

        session = _Session(handler)
        resolver = MultilingualPokemonCardResolver(session=session)
        result = resolver.resolve_identity(
            CardIdentity(
                game="Pokémon TCG",
                card_name="Ekans",
                set="Fossil",
                card_number="46/62",
                language="French",
            )
        )

        self.assertTrue(result.matched)
        self.assertFalse(result.ambiguous)
        self.assertEqual(result.source, "TCGDEX")
        self.assertEqual(result.identity.card_name, "Abo")
        self.assertEqual(result.identity.set, "Fossile")
        self.assertEqual(result.identity.card_number, "46/62")
        self.assertEqual(result.identity.language, "French")
        self.assertEqual(result.identity.year, 1999)
        self.assertEqual(resolver.counters.pokemon_tcg_requests, 0)

    def test_non_english_tcgdex_miss_does_not_cross_language_fallback(self):
        def handler(url, _params, _headers):
            if url.endswith("/fr/sets") or url.endswith("/en/sets"):
                return _Response(200, [])
            raise AssertionError("Pokémon TCG API must not overwrite known French identity")

        session = _Session(handler)
        resolver = MultilingualPokemonCardResolver(session=session)
        result = resolver.resolve_identity(
            CardIdentity(
                game="Pokémon TCG",
                set="Set introuvable",
                card_number="1/100",
                language="French",
            )
        )

        self.assertFalse(result.matched)
        self.assertFalse(result.ambiguous)
        self.assertEqual(resolver.counters.pokemon_tcg_requests, 0)

    def test_english_tcgdex_miss_uses_pokemon_tcg_api_fallback(self):
        def handler(url, _params, _headers):
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
            raise AssertionError(f"unexpected request: {url}")

        resolver = MultilingualPokemonCardResolver(session=_Session(handler))
        result = resolver.resolve_identity(
            CardIdentity(
                game="Pokémon TCG",
                set="Base Set",
                card_number="4/102",
                language="English",
            )
        )

        self.assertTrue(result.matched)
        self.assertEqual(result.source, "POKEMON_TCG")
        self.assertEqual(result.identity.card_name, "Charizard")
        self.assertEqual(result.identity.language, "English")
        self.assertEqual(resolver.counters.pokemon_tcg_hits, 1)

    def test_multiple_tcgdex_set_candidates_are_rejected_as_ambiguous(self):
        def handler(url, _params, _headers):
            if url.endswith("/en/sets"):
                return _Response(
                    200,
                    [
                        {"id": "set-a", "name": "Mystery Set A"},
                        {"id": "set-b", "name": "Mystery Set B"},
                    ],
                )
            if url.endswith("/fr/sets"):
                return _Response(200, [])
            raise AssertionError("ambiguous set candidates must not open a card")

        resolver = MultilingualPokemonCardResolver(session=_Session(handler))
        result = resolver.resolve_identity(
            CardIdentity(
                game="Pokémon TCG",
                set="Mystery Set",
                card_number="10/100",
                language="English",
            )
        )

        self.assertFalse(result.matched)
        self.assertTrue(result.ambiguous)
        self.assertEqual(resolver.counters.ambiguous, 1)
        self.assertEqual(resolver.counters.pokemon_tcg_requests, 0)


if __name__ == "__main__":
    unittest.main()
