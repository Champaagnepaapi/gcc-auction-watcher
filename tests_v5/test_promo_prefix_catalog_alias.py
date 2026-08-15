from __future__ import annotations

import unittest

from v5.card_identity_catalog import (
    MultilingualPokemonCardResolver,
    _deterministic_promo_set_id,
    _local_card_number_candidates,
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
        self.calls.append((url, params or {}, headers or {}))
        return self.handler(url, params or {}, headers or {})


class PromoPrefixCatalogAliasTests(unittest.TestCase):
    def test_dp_prefix_requires_matching_prefixed_collector_number(self):
        self.assertEqual(_deterministic_promo_set_id("DP", "DP045"), "dpp")
        self.assertEqual(_deterministic_promo_set_id("dp", "DP45"), "dpp")
        self.assertIsNone(_deterministic_promo_set_id("DP", "45"))
        self.assertIsNone(_deterministic_promo_set_id("DP", "XY045"))
        self.assertIsNone(_deterministic_promo_set_id("Promo Cards", "DP045"))

    def test_prefixed_local_id_zero_normalization_is_deterministic(self):
        self.assertEqual(
            _local_card_number_candidates("DP045"),
            ("DP045", "DP45"),
        )
        self.assertEqual(
            _local_card_number_candidates("swsh027"),
            ("swsh027", "SWSH027", "SWSH27"),
        )
        self.assertEqual(_local_card_number_candidates("TG03/TG30"), ("TG03",))
        self.assertEqual(_local_card_number_candidates("089"), ("089", "89"))

    def test_exact_dp_alias_resolves_only_via_exact_dpp_set_and_dp45_card(self):
        def handler(url, _params, _headers):
            if url.endswith("/en/sets"):
                return _Response(
                    200,
                    [{"id": "dpp", "name": "DP Black Star Promos", "cardCount": {"official": 56}}],
                )
            if url.endswith("/fr/sets"):
                return _Response(200, [])
            if url.endswith("/en/sets/dpp/DP045") or url.endswith("/en/cards/dpp-DP045"):
                return _Response(404, {})
            if url.endswith("/en/sets/dpp/DP45"):
                return _Response(
                    200,
                    {
                        "id": "dpp-DP45",
                        "name": "Charizard G",
                        "localId": "DP45",
                        "variants": {
                            "firstEdition": False,
                            "holo": True,
                            "normal": False,
                            "reverse": False,
                            "wPromo": False,
                        },
                        "set": {
                            "id": "dpp",
                            "name": "DP Black Star Promos",
                            "cardCount": {"official": 56},
                            "releaseDate": "2009-01-01",
                        },
                    },
                )
            raise AssertionError(f"unexpected request: {url}")

        resolver = MultilingualPokemonCardResolver(session=_Session(handler))
        result = resolver.resolve_identity(
            CardIdentity(
                game="Pokémon TCG",
                card_name="Dracaufeu",
                set="DP",
                card_number="DP045",
                language="English",
                finish="Holo",
            )
        )

        self.assertTrue(result.matched)
        self.assertFalse(result.ambiguous)
        self.assertEqual(result.source, "TCGDEX")
        self.assertEqual(result.identity.card_name, "Charizard G")
        self.assertEqual(result.identity.set, "DP Black Star Promos")
        # The exact TCGdex localId DP45 proves equivalence, but V5 preserves the
        # seller spelling DP045 rather than rewriting a denominatorless promo ID.
        self.assertEqual(result.identity.card_number, "DP045")
        self.assertEqual(result.set_provenance.local_id, "DP45")
        self.assertEqual(result.microvariant_applicability.source, "TCGDEX_EXACT")
        self.assertTrue(result.microvariant_applicability.finish_proven_single)
        self.assertEqual(result.microvariant_applicability.single_finish, "holofoil")
        self.assertEqual(resolver.counters.tcgdex_local_id_alternate_hits, 1)

    def test_short_dp_set_without_dp_prefixed_number_does_not_use_alias(self):
        def handler(url, _params, _headers):
            if url.endswith("/en/sets") or url.endswith("/fr/sets"):
                return _Response(
                    200,
                    [{"id": "dpp", "name": "DP Black Star Promos"}],
                )
            if url.endswith("/v2/cards"):
                return _Response(200, {"data": []})
            raise AssertionError(f"promo-set card route must not be called: {url}")

        resolver = MultilingualPokemonCardResolver(session=_Session(handler))
        result = resolver.resolve_identity(
            CardIdentity(
                game="Pokémon TCG",
                card_name="Charizard G",
                set="DP",
                card_number="45",
                language="English",
            )
        )

        self.assertFalse(result.matched)
        self.assertFalse(result.ambiguous)
        self.assertEqual(resolver.counters.tcgdex_hits, 0)

    def test_mismatched_prefix_cannot_cross_into_dp_promo_set(self):
        self.assertIsNone(_deterministic_promo_set_id("DP", "SWSH045"))
        self.assertIsNone(_deterministic_promo_set_id("SWSH", "DP045"))


if __name__ == "__main__":
    unittest.main()
