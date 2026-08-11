from __future__ import annotations

import unittest

import requests

from v5.card_identity_catalog import (
    MultilingualPokemonCardResolver,
    _language_code,
    _local_card_number_candidates,
)
from v5.models import CardIdentity


class Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class Session:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(url)
        value = self.handler(url)
        if isinstance(value, Exception):
            raise value
        return value


def identity(*, number="004/102", language="English", finish=None):
    return CardIdentity(
        game="Pokemon TCG",
        card_name="Charizard",
        set="Base Set",
        card_number=number,
        language=language,
        finish=finish,
    )


def card(local_id="4", *, variants=None):
    payload = {
        "name": "Charizard",
        "localId": local_id,
        "set": {
            "id": "base1",
            "name": "Base Set",
            "releaseDate": "1999-01-09",
            "cardCount": {"official": 102, "total": 102},
        },
    }
    if variants is not None:
        payload["variants"] = variants
    return payload


class TCGdexResolutionRegressionTests(unittest.TestCase):
    def test_numeric_local_id_gets_safe_unpadded_alternate(self):
        self.assertEqual(_local_card_number_candidates("004/102"), ("004", "4"))
        self.assertEqual(_local_card_number_candidates("4/102"), ("4",))

    def test_prefixed_local_id_only_gets_case_alternate(self):
        self.assertEqual(_local_card_number_candidates("sv107/sv122"), ("sv107", "SV107"))
        self.assertEqual(_local_card_number_candidates("TG03/TG30"), ("TG03",))

    def test_unsupported_language_uses_english_metadata_endpoint(self):
        self.assertIsNone(_language_code("Korean"))
        calls = []

        def handler(url):
            calls.append(url)
            if url.endswith("/en/sets"):
                return Response(200, [{"id": "base1", "name": "Base Set"}])
            if url.endswith("/fr/sets"):
                return Response(200, [])
            if url.endswith("/en/sets/base1/4"):
                return Response(200, card("4"))
            if "/ko/" in url:
                raise AssertionError("unsupported Korean endpoint must not be called")
            return Response(404, {})

        resolver = MultilingualPokemonCardResolver(session=Session(handler))
        result = resolver.resolve_identity(identity(number="4/102", language="Korean"))
        self.assertTrue(result.matched)
        self.assertEqual(result.identity.language, "Korean")
        self.assertEqual(resolver.counters.tcgdex_unsupported_language_fallbacks, 1)
        self.assertFalse(any("/ko/" in url for url in calls))

    def test_unpadded_local_id_can_rescue_padded_marketplace_number(self):
        def handler(url):
            if url.endswith("/en/sets"):
                return Response(200, [{"id": "base1", "name": "Base Set"}])
            if url.endswith("/fr/sets"):
                return Response(200, [])
            if url.endswith("/en/sets/base1/004"):
                return Response(404, {})
            if url.endswith("/en/cards/base1-004"):
                return Response(404, {})
            if url.endswith("/en/sets/base1/4"):
                return Response(200, card("4"))
            return Response(404, {})

        resolver = MultilingualPokemonCardResolver(session=Session(handler))
        result = resolver.resolve_identity(identity())
        self.assertTrue(result.matched)
        self.assertEqual(resolver.counters.tcgdex_local_id_alternates_tried, 1)
        self.assertEqual(resolver.counters.tcgdex_local_id_alternate_hits, 1)

    def test_direct_card_route_can_rescue_set_route_404(self):
        def handler(url):
            if url.endswith("/en/sets"):
                return Response(200, [{"id": "base1", "name": "Base Set"}])
            if url.endswith("/fr/sets"):
                return Response(200, [])
            if url.endswith("/en/sets/base1/4"):
                return Response(404, {})
            if url.endswith("/en/cards/base1-4"):
                return Response(200, card("4"))
            return Response(404, {})

        resolver = MultilingualPokemonCardResolver(session=Session(handler))
        result = resolver.resolve_identity(identity(number="4/102"))
        self.assertTrue(result.matched)
        self.assertEqual(resolver.counters.tcgdex_direct_card_fallbacks, 1)
        self.assertEqual(resolver.counters.tcgdex_direct_card_hits, 1)

    def test_failure_buckets_separate_set_catalog_and_card_lookup(self):
        def handler(url):
            if url.endswith("/en/sets"):
                return Response(500, {})
            if url.endswith("/fr/sets"):
                return Response(200, [{"id": "base1", "name": "Base Set"}])
            if "/fr/sets/base1/" in url:
                return Response(500, {})
            if "/fr/cards/base1-" in url:
                return Response(404, {})
            if "/en/sets/base1/" in url:
                return Response(404, {})
            if "/en/cards/base1-" in url:
                return Response(404, {})
            return Response(404, {})

        resolver = MultilingualPokemonCardResolver(session=Session(handler))
        resolver.resolve_identity(identity(language="French", number="4/102"))
        self.assertGreaterEqual(resolver.counters.tcgdex_http_failures, 2)
        self.assertGreaterEqual(resolver.counters.tcgdex_set_catalog_failures, 1)
        self.assertGreaterEqual(resolver.counters.tcgdex_card_lookup_failures, 1)

    def test_tcgdex_variant_false_is_ambiguous_not_silently_accepted(self):
        variants = {
            "firstEdition": False,
            "holo": False,
            "normal": True,
            "reverse": True,
            "wPromo": False,
        }

        def handler(url):
            if url.endswith("/en/sets"):
                return Response(200, [{"id": "base1", "name": "Base Set"}])
            if url.endswith("/fr/sets"):
                return Response(200, [])
            if url.endswith("/en/sets/base1/4"):
                return Response(200, card("4", variants=variants))
            return Response(404, {})

        resolver = MultilingualPokemonCardResolver(session=Session(handler))
        result = resolver.resolve_identity(identity(number="4/102", finish="Holo"))
        self.assertFalse(result.matched)
        self.assertTrue(result.ambiguous)
        self.assertFalse(result.blocking)
        self.assertEqual(resolver.counters.tcgdex_variant_impossible, 1)


if __name__ == "__main__":
    unittest.main()
