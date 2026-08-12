from __future__ import annotations

import unittest

from v5.card_identity_catalog import CatalogIdentityResult
from v5.card_identity_uniqueness import (
    DeterministicUniquenessHybridPokemonCardResolver,
)
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
        params = params or {}
        self.calls.append((url, params))
        return self.handler(url, params)


class _PokeTraceIdentity:
    def __init__(self):
        self.resolve_calls = 0
        self.set_provenance = []
        self.aliases = []

    def has_deterministic_alias(self, _identity):
        return False

    def resolve_identity(self, identity):
        self.resolve_calls += 1
        return type(
            "Resolution",
            (),
            {"identity": identity, "matched": False, "ambiguous": False},
        )()

    def register_set_provenance(self, identity, provenance):
        self.set_provenance.append((identity, provenance))
        return True

    def register_provider_alias(self, identity, alias):
        self.aliases.append((identity, alias))
        return True

    def alias_cached_result(self, *_args, **_kwargs):
        return None


def full_card(card_id, name, local_id, set_id, set_name, official, **extra):
    payload = {
        "id": card_id,
        "name": name,
        "localId": local_id,
        "set": {
            "id": set_id,
            "name": set_name,
            "cardCount": {"official": official, "total": official},
            "releaseDate": extra.pop("releaseDate", "2000-01-01"),
        },
        "variants": extra.pop(
            "variants",
            {
                "firstEdition": False,
                "holo": True,
                "normal": False,
                "reverse": False,
                "wPromo": False,
            },
        ),
    }
    payload.update(extra)
    return payload


class DeterministicCatalogUniquenessTests(unittest.TestCase):
    def resolver(self, handler):
        poketrace = _PokeTraceIdentity()
        return (
            DeterministicUniquenessHybridPokemonCardResolver(
                poketrace_identity_resolver=poketrace,
                session=_Session(handler),
            ),
            poketrace,
        )

    def test_lugia_name_plus_full_number_uniquely_recovers_neo_genesis(self):
        def handler(url, params):
            if url.endswith("/en/cards"):
                self.assertEqual(params["localId"], "eq:9")
                return _Response(
                    200,
                    [{"id": "neo1-9", "localId": "9", "name": "Lugia"}],
                )
            if url.endswith("/en/cards/neo1-9"):
                return _Response(
                    200,
                    full_card(
                        "neo1-9", "Lugia", "9", "neo1", "Neo Genesis", 111,
                        releaseDate="2000-12-16",
                    ),
                )
            raise AssertionError(f"unexpected request {url} {params}")

        resolver, poketrace = self.resolver(handler)
        result = resolver.resolve_identity(
            CardIdentity(
                game="Pokémon TCG",
                card_name="Lugia",
                card_number="9/111",
                language="English",
            )
        )

        self.assertTrue(result.matched)
        self.assertFalse(result.ambiguous)
        self.assertEqual(result.source, "TCGDEX")
        self.assertEqual(result.identity.set, "Neo Genesis")
        self.assertEqual(result.identity.card_number, "9/111")
        self.assertEqual(result.identity.language, "English")
        self.assertEqual(resolver.uniqueness_counters.name_number_hits, 1)
        self.assertEqual(resolver.uniqueness_counters.recovered_sets, 1)
        self.assertEqual(poketrace.resolve_calls, 0)
        self.assertTrue(poketrace.set_provenance)

    def test_post_macro_applicability_can_use_exact_name_number_uniqueness(self):
        def handler(url, params):
            if url.endswith("/en/sets"):
                return _Response(200, [{"id": "me01", "name": "Mega Evolution"}])
            if url.endswith("/fr/sets"):
                return _Response(200, [])
            if url.endswith("/en/cards"):
                self.assertEqual(params["localId"], "eq:154")
                return _Response(
                    200,
                    [{"id": "me01-154", "localId": "154", "name": "Stufful"}],
                )
            if url.endswith("/en/cards/me01-154"):
                return _Response(
                    200,
                    full_card(
                        "me01-154",
                        "Stufful",
                        "154",
                        "me01",
                        "Mega Evolution",
                        132,
                        variants={
                            "firstEdition": False,
                            "normal": False,
                            "holo": True,
                            "reverse": False,
                        },
                    ),
                )
            raise AssertionError(f"unexpected request {url} {params}")

        resolver, poketrace = self.resolver(handler)
        applicability = resolver.resolve_microvariant_applicability(
            CardIdentity(
                game="Pokémon TCG",
                card_name="Stufful",
                set="ME01: Mega Evolution",
                card_number="154/132",
                language="English",
            )
        )
        self.assertEqual(applicability.source, "TCGDEX_EXACT")
        self.assertTrue(applicability.finish_proven_single)
        self.assertEqual(applicability.single_finish, "holofoil")
        self.assertTrue(applicability.edition_proven_single)
        self.assertEqual(resolver.counters.post_macro_exact_finish_single, 1)
        self.assertEqual(resolver.counters.post_macro_applicability_resolved, 1)
        self.assertEqual(resolver.counters.post_macro_applicability_unknown, 0)
        self.assertEqual(poketrace.resolve_calls, 0)

    def test_post_macro_applicability_rejects_unique_card_from_unrelated_set(self):
        def handler(url, params):
            if url.endswith("/en/sets"):
                return _Response(200, [])
            if url.endswith("/fr/sets"):
                return _Response(200, [])
            if url.endswith("/en/cards"):
                return _Response(
                    200,
                    [{"id": "me01-154", "localId": "154", "name": "Stufful"}],
                )
            if url.endswith("/en/cards/me01-154"):
                return _Response(
                    200,
                    full_card(
                        "me01-154",
                        "Stufful",
                        "154",
                        "me01",
                        "Mega Evolution",
                        132,
                        variants={
                            "firstEdition": False,
                            "normal": True,
                            "holo": False,
                            "reverse": False,
                        },
                    ),
                )
            raise AssertionError(f"unexpected request {url} {params}")

        resolver, _poketrace = self.resolver(handler)
        applicability = resolver.resolve_microvariant_applicability(
            CardIdentity(
                game="Pokémon TCG",
                card_name="Stufful",
                set="Completely Unrelated Set",
                card_number="154/132",
                language="English",
            )
        )
        self.assertEqual(
            applicability.status,
            "MICROVARIANT_APPLICABILITY_UNKNOWN",
        )

    def test_post_macro_applicability_stays_unknown_if_name_number_not_unique(self):
        def handler(url, params):
            if url.endswith("/en/sets") or url.endswith("/fr/sets"):
                return _Response(200, [])
            if url.endswith("/en/cards"):
                return _Response(
                    200,
                    [
                        {"id": "seta-154", "localId": "154", "name": "Stufful"},
                        {"id": "setb-154", "localId": "154", "name": "Stufful"},
                    ],
                )
            if url.endswith("/en/cards/seta-154"):
                return _Response(
                    200,
                    full_card("seta-154", "Stufful", "154", "seta", "Set A", 132),
                )
            if url.endswith("/en/cards/setb-154"):
                return _Response(
                    200,
                    full_card("setb-154", "Stufful", "154", "setb", "Set B", 132),
                )
            raise AssertionError(f"unexpected request {url} {params}")

        resolver, _poketrace = self.resolver(handler)
        applicability = resolver.resolve_microvariant_applicability(
            CardIdentity(
                game="Pokémon TCG",
                card_name="Stufful",
                set="Provider Set Label",
                card_number="154/132",
                language="English",
            )
        )
        self.assertEqual(
            applicability.status,
            "MICROVARIANT_APPLICABILITY_UNKNOWN",
        )

    def test_post_macro_applicability_does_not_default_unknown_language_to_english(self):
        def handler(url, params):
            if url.endswith("/en/sets") or url.endswith("/fr/sets"):
                return _Response(200, [])
            raise AssertionError(
                f"unsupported language must not trigger exact-name/number applicability retry: {url} {params}"
            )

        resolver, _poketrace = self.resolver(handler)
        applicability = resolver.resolve_microvariant_applicability(
            CardIdentity(
                game="Pokémon TCG",
                card_name="Stufful",
                set="ME01: Mega Evolution",
                card_number="154/132",
                language=None,
            )
        )
        self.assertEqual(
            applicability.status,
            "MICROVARIANT_APPLICABILITY_UNKNOWN",
        )

    def test_same_9_over_111_number_can_resolve_accelgor_only_with_exact_name(self):
        def handler(url, _params):
            if url.endswith("/en/cards"):
                return _Response(
                    200,
                    [{"id": "xy3-9", "localId": "9", "name": "Accelgor"}],
                )
            if url.endswith("/en/cards/xy3-9"):
                return _Response(
                    200,
                    full_card(
                        "xy3-9", "Accelgor", "9", "xy3", "Furious Fists", 111,
                        releaseDate="2014-08-13",
                    ),
                )
            raise AssertionError(f"unexpected request {url}")

        resolver, _poketrace = self.resolver(handler)
        result = resolver.resolve_identity(
            CardIdentity(
                game="Pokémon TCG",
                card_name="Accelgor",
                card_number="9/111",
                language="English",
            )
        )
        self.assertTrue(result.matched)
        self.assertEqual(result.identity.set, "Furious Fists")

    def test_number_alone_never_triggers_catalog_uniqueness(self):
        def handler(url, _params):
            raise AssertionError(f"single number must not make a catalogue request: {url}")

        resolver, poketrace = self.resolver(handler)
        result = resolver.resolve_identity(
            CardIdentity(
                game="Pokémon TCG",
                card_number="9/111",
                language="English",
            )
        )
        self.assertFalse(result.matched)
        self.assertFalse(result.ambiguous)
        self.assertEqual(resolver.uniqueness_counters.attempts, 0)
        self.assertEqual(poketrace.resolve_calls, 0)

    def test_name_plus_full_number_is_ambiguous_if_two_exact_macro_cards_remain(self):
        def handler(url, _params):
            if url.endswith("/en/cards"):
                return _Response(
                    200,
                    [
                        {"id": "seta-9", "localId": "9", "name": "Fixturemon"},
                        {"id": "setb-9", "localId": "9", "name": "Fixturemon"},
                    ],
                )
            if url.endswith("/en/cards/seta-9"):
                return _Response(200, full_card("seta-9", "Fixturemon", "9", "seta", "Set A", 111))
            if url.endswith("/en/cards/setb-9"):
                return _Response(200, full_card("setb-9", "Fixturemon", "9", "setb", "Set B", 111))
            raise AssertionError(f"unexpected request {url}")

        resolver, poketrace = self.resolver(handler)
        result = resolver.resolve_identity(
            CardIdentity(
                game="Pokémon TCG",
                card_name="Fixturemon",
                card_number="9/111",
                language="English",
            )
        )
        self.assertFalse(result.matched)
        self.assertTrue(result.ambiguous)
        self.assertEqual(resolver.uniqueness_counters.name_number_ambiguous, 1)
        self.assertEqual(poketrace.resolve_calls, 0)

    def test_denominator_conflict_cannot_recover_set(self):
        def handler(url, _params):
            if url.endswith("/en/cards"):
                return _Response(
                    200,
                    [{"id": "wrong-9", "localId": "9", "name": "Lugia"}],
                )
            if url.endswith("/en/cards/wrong-9"):
                return _Response(200, full_card("wrong-9", "Lugia", "9", "wrong", "Wrong Set", 102))
            raise AssertionError(f"unexpected request {url}")

        resolver, poketrace = self.resolver(handler)
        result = resolver.resolve_identity(
            CardIdentity(
                game="Pokémon TCG",
                card_name="Lugia",
                card_number="9/111",
                language="English",
            )
        )
        self.assertFalse(result.matched)
        self.assertEqual(resolver.uniqueness_counters.name_number_no_match, 1)
        # Clean no-match may continue to the already-existing PokeTrace lane.
        self.assertEqual(poketrace.resolve_calls, 1)

    def test_numerator_only_name_number_is_not_enough_to_recover_set(self):
        def handler(url, _params):
            raise AssertionError(f"numerator-only must not run uniqueness: {url}")

        resolver, poketrace = self.resolver(handler)
        result = resolver.resolve_identity(
            CardIdentity(
                game="Pokémon TCG",
                card_name="Lugia",
                card_number="9",
                language="English",
            )
        )
        self.assertFalse(result.matched)
        self.assertEqual(resolver.uniqueness_counters.attempts, 0)
        self.assertEqual(poketrace.resolve_calls, 1)

    def test_exact_set_plus_unique_name_recovers_printed_number(self):
        def handler(url, _params):
            if url.endswith("/en/sets"):
                return _Response(200, [{"id": "neo1", "name": "Neo Genesis", "cardCount": {"official": 111}}])
            if url.endswith("/fr/sets"):
                return _Response(200, [])
            if url.endswith("/en/sets/neo1"):
                return _Response(
                    200,
                    {
                        "id": "neo1",
                        "name": "Neo Genesis",
                        "cardCount": {"official": 111},
                        "cards": [
                            {"id": "neo1-9", "localId": "9", "name": "Lugia"},
                            {"id": "neo1-22", "localId": "22", "name": "Elekid"},
                        ],
                    },
                )
            if url.endswith("/en/cards/neo1-9"):
                return _Response(200, full_card("neo1-9", "Lugia", "9", "neo1", "Neo Genesis", 111))
            raise AssertionError(f"unexpected request {url}")

        resolver, poketrace = self.resolver(handler)
        result = resolver.resolve_identity(
            CardIdentity(
                game="Pokémon TCG",
                card_name="Lugia",
                set="Neo Genesis",
                language="English",
            )
        )
        self.assertTrue(result.matched)
        self.assertEqual(result.identity.card_number, "9/111")
        self.assertEqual(resolver.uniqueness_counters.set_name_hits, 1)
        self.assertEqual(resolver.uniqueness_counters.recovered_numbers, 1)
        self.assertEqual(poketrace.resolve_calls, 0)

    def test_exact_set_plus_name_is_ambiguous_when_name_occurs_twice_in_set(self):
        def handler(url, _params):
            if url.endswith("/en/sets"):
                return _Response(200, [{"id": "fixture", "name": "Fixture Set"}])
            if url.endswith("/fr/sets"):
                return _Response(200, [])
            if url.endswith("/en/sets/fixture"):
                return _Response(
                    200,
                    {
                        "cards": [
                            {"id": "fixture-1", "localId": "1", "name": "Pikachu"},
                            {"id": "fixture-99", "localId": "99", "name": "Pikachu"},
                        ]
                    },
                )
            raise AssertionError(f"unexpected request {url}")

        resolver, poketrace = self.resolver(handler)
        result = resolver.resolve_identity(
            CardIdentity(
                game="Pokémon TCG",
                card_name="Pikachu",
                set="Fixture Set",
                language="English",
            )
        )
        self.assertFalse(result.matched)
        self.assertTrue(result.ambiguous)
        self.assertEqual(resolver.uniqueness_counters.set_name_ambiguous, 1)
        self.assertEqual(poketrace.resolve_calls, 0)

    def test_macro_uniqueness_does_not_inherit_first_edition_or_finish(self):
        def handler(url, _params):
            if url.endswith("/en/cards"):
                return _Response(200, [{"id": "neo1-9", "localId": "9", "name": "Lugia"}])
            if url.endswith("/en/cards/neo1-9"):
                return _Response(
                    200,
                    full_card(
                        "neo1-9",
                        "Lugia",
                        "9",
                        "neo1",
                        "Neo Genesis",
                        111,
                        variants={
                            "firstEdition": True,
                            "holo": True,
                            "normal": False,
                            "reverse": False,
                            "wPromo": False,
                        },
                    ),
                )
            raise AssertionError(f"unexpected request {url}")

        resolver, _poketrace = self.resolver(handler)
        original = CardIdentity(
            game="Pokémon TCG",
            card_name="Lugia",
            card_number="9/111",
            language="English",
        )
        result = resolver.resolve_identity(original)
        self.assertTrue(result.matched)
        self.assertIsNone(result.identity.edition)
        self.assertIsNone(result.identity.finish)
        self.assertEqual(result.identity.language, "English")


if __name__ == "__main__":
    unittest.main()
