from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal

from v5.card_identity_catalog import (
    HybridPokemonCardResolver,
    MultilingualPokemonCardResolver,
)
from v5.live_raw_pipeline_catalog import _PokeTracePrimaryMarketSource
from v5.market_values.poketrace import PokeTraceConfig
from v5.market_values.poketrace_free import FreeTierPokeTraceProvider
from v5.models import (
    POKETRACE_PROVIDER,
    TCGDEX_EXACT_ENGLISH_TWIN,
    CardIdentity,
    ProviderSearchAlias,
)
from v5.poketrace_identity import PokeTraceIdentityResolver


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.headers = {}

    def json(self):
        return self._payload


class _CatalogSession:
    def __init__(self, english_twin=...):
        self.english_twin = english_twin
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params or {}, headers or {}))
        if url.endswith("/fr/sets"):
            return _Response(200, [{"id": "base1", "name": "Set de Base"}])
        if url.endswith("/en/sets"):
            return _Response(200, [{"id": "base1", "name": "Base Set"}])
        if url.endswith("/fr/sets/base1/6"):
            return _Response(200, _localized_card())
        if url.endswith("/en/cards/base1-6"):
            twin = _english_card() if self.english_twin is ... else self.english_twin
            return _Response(200 if twin is not None else 404, twin)
        raise AssertionError(f"unexpected offline catalogue request: {url}")


class _PokeTraceSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.payloads:
            raise AssertionError("unexpected offline PokeTrace request")
        return _Response(200, self.payloads.pop(0))


def _localized_card():
    return {
        "id": "base1-6",
        "name": "Léviator",
        "localId": "6",
        "set": {
            "id": "base1",
            "name": "Set de Base",
            "releaseDate": "1999-01-09",
            "cardCount": {"official": 102},
        },
    }


def _english_card(**overrides):
    card = {
        "id": "base1-6",
        "name": "Gyarados",
        "localId": "6",
        "set": {
            "id": "base1",
            "name": "Base Set",
            "releaseDate": "1999-01-09",
            "cardCount": {"official": 102},
        },
    }
    card.update(overrides)
    return card


def _french_identity(variant=None):
    return CardIdentity(
        game="Pokémon TCG",
        card_name="Léviator",
        set="Set de Base",
        card_number="6/102",
        language="French",
        variant=variant,
    )


def _provider_alias():
    return ProviderSearchAlias(
        provider=POKETRACE_PROVIDER,
        search_card_name="Gyarados",
        search_set_name="Base Set",
        provenance=TCGDEX_EXACT_ENGLISH_TWIN,
        catalog_card_id="base1-6",
        catalog_set_id="base1",
        catalog_local_id="6",
    )


def _poketrace_card(*, set_name="Base Set", number="006/102", variant=None):
    return {
        "id": "pt-base1-6",
        "name": "Gyarados",
        "cardNumber": number,
        "set": {"name": set_name, "slug": "base-set"},
        "variant": variant,
        "productType": "single",
        "market": "US",
        "currency": "USD",
        "prices": {
            "ebay": {"NEAR_MINT": {"median7d": 30}},
            "tcgplayer": {"NEAR_MINT": {"median7d": 34}},
        },
    }


def _market(session):
    return FreeTierPokeTraceProvider(
        PokeTraceConfig(
            enabled=True,
            api_key="offline-placeholder",
            minimum_request_interval_seconds=0,
        ),
        session=session,
    )


class DeterministicMultilingualAliasTests(unittest.TestCase):
    def test_exact_french_and_english_twin_same_coordinates_allows_alias(self):
        resolver = MultilingualPokemonCardResolver(session=_CatalogSession())

        result = resolver.resolve_identity(_french_identity())

        self.assertTrue(result.matched)
        self.assertEqual(result.identity.card_name, "Léviator")
        self.assertEqual(result.identity.language, "French")
        self.assertEqual(result.provider_alias, _provider_alias())
        self.assertEqual(resolver.counters.localized_identities_seen, 1)
        self.assertEqual(resolver.counters.deterministic_english_aliases_found, 1)

    def test_different_id_set_or_local_id_forbids_alias(self):
        twins = {
            "card id": _english_card(id="other-6"),
            "set id": _english_card(
                set={"id": "base2", "name": "Base Set 2"}
            ),
            "local id": _english_card(localId="7"),
        }
        for label, twin in twins.items():
            with self.subTest(label=label):
                resolver = MultilingualPokemonCardResolver(
                    session=_CatalogSession(twin)
                )
                result = resolver.resolve_identity(_french_identity())
                self.assertTrue(result.matched)
                self.assertIsNone(result.provider_alias)
                self.assertEqual(
                    resolver.counters.alias_unavailable_no_exact_english_twin,
                    1,
                )

    def test_missing_exact_english_twin_creates_no_alias(self):
        resolver = MultilingualPokemonCardResolver(
            session=_CatalogSession(None)
        )

        result = resolver.resolve_identity(_french_identity())

        self.assertTrue(result.matched)
        self.assertIsNone(result.provider_alias)
        self.assertEqual(
            resolver.counters.alias_unavailable_no_exact_english_twin,
            1,
        )

    def test_french_tcgdex_exact_gets_raw_value_via_english_provider_alias(self):
        provider_session = _PokeTraceSession(
            [{"data": [_poketrace_card()]}]
        )
        market = _market(provider_session)
        identity_resolver = PokeTraceIdentityResolver(market)
        catalog = HybridPokemonCardResolver(
            poketrace_identity_resolver=identity_resolver,
            session=_CatalogSession(),
        )

        resolved = catalog.resolve_identity(_french_identity())
        values = _PokeTracePrimaryMarketSource(market).values_for(
            resolved.identity
        )

        self.assertTrue(resolved.matched)
        self.assertEqual(identity_resolver.counters.queries, 0)
        self.assertEqual(catalog.counters.tcgdex_poketrace_calls_avoided, 1)
        self.assertEqual(
            catalog.counters.alias_identity_calls_avoided_by_tcgdex_exact,
            1,
        )
        self.assertEqual(len(provider_session.calls), 1)
        params = provider_session.calls[0][1]["params"]
        self.assertEqual(params["search"], "Gyarados")
        self.assertEqual(params["card_number"], "6/102")
        self.assertEqual(values.ungraded_value, Decimal("32"))
        self.assertEqual(values.matched_identity.card_name, "Léviator")
        self.assertEqual(values.matched_identity.set, "Set de Base")
        self.assertEqual(values.matched_identity.language, "French")
        self.assertEqual(market.counters.provider_alias_market_searches, 1)
        self.assertEqual(market.counters.alias_market_matches, 1)

    def test_alias_never_accepts_same_name_with_wrong_set_or_number(self):
        wrong_set = _poketrace_card(set_name="Jungle")
        wrong_set["set"] = {"name": "Jungle", "slug": "jungle"}
        candidates = (
            wrong_set,
            _poketrace_card(number="007/102"),
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                session = _PokeTraceSession([{"data": [candidate]}])
                market = _market(session)
                identity = _french_identity()
                self.assertTrue(
                    market.register_search_alias(identity, _provider_alias())
                )

                snapshot = market.snapshot_for(identity)

                self.assertIsNone(snapshot.us_values)
                self.assertEqual(market.counters.alias_market_matches, 0)

    def test_french_unresolved_without_alias_is_not_poketrace_eligible(self):
        class _EmptyCatalogSession:
            def get(self, url, **_kwargs):
                if url.endswith("/fr/sets") or url.endswith("/en/sets"):
                    return _Response(200, [])
                raise AssertionError(f"unexpected catalogue request: {url}")

        provider_session = _PokeTraceSession([])
        market = _market(provider_session)
        catalog = HybridPokemonCardResolver(
            poketrace_identity_resolver=PokeTraceIdentityResolver(market),
            session=_EmptyCatalogSession(),
        )

        result = catalog.resolve_identity(_french_identity())

        self.assertFalse(result.matched)
        self.assertEqual(provider_session.calls, [])
        self.assertFalse(market.has_search_alias(_french_identity()))

    def test_identity_search_uses_alias_but_returns_localized_identity(self):
        session = _PokeTraceSession([{"data": [_poketrace_card()]}])
        market = _market(session)
        identity = _french_identity()
        market.register_search_alias(identity, _provider_alias())
        resolver = PokeTraceIdentityResolver(market)

        result = resolver.resolve_identity(identity)

        self.assertTrue(result.matched)
        self.assertEqual(result.identity, identity)
        self.assertEqual(session.calls[0][1]["params"]["search"], "Gyarados Base Set 6/102")
        self.assertEqual(resolver.counters.provider_alias_identity_searches, 1)
        self.assertEqual(resolver.counters.alias_identity_matches, 1)

    def test_cache_separates_alias_state_localized_name_and_variant(self):
        holo = _french_identity("Holofoil")
        reverse = _french_identity("Reverse Holofoil")
        english = replace(
            holo,
            card_name="Gyarados",
            set="Base Set",
            language="English",
        )
        session = _PokeTraceSession(
            [
                {"data": [_poketrace_card(variant="Holofoil")]},
                {"data": [_poketrace_card(variant="Reverse Holofoil")]},
                {"data": [_poketrace_card(variant="Holofoil")]},
            ]
        )
        market = _market(session)
        market.register_search_alias(holo, _provider_alias())
        market.register_search_alias(reverse, _provider_alias())

        first = market.snapshot_for(holo)
        cached = market.snapshot_for(holo)
        second_variant = market.snapshot_for(reverse)
        english_identity = market.snapshot_for(english)

        self.assertIsNotNone(first.us_values)
        self.assertEqual(first, cached)
        self.assertIsNotNone(second_variant.us_values)
        self.assertIsNotNone(english_identity.us_values)
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(market.counters.cache_hits, 1)


if __name__ == "__main__":
    unittest.main()
