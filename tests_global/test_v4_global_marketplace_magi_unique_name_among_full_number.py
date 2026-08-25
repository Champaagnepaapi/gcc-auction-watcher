from __future__ import annotations

import unittest
from unittest import mock

import japan_edge_hunter as japan
import v4_global_market_core as core
import v4_global_marketplace_magi_native_identity as native
import v4_global_marketplace_magi_unique_name_among_full_number as unique_name
import v4_global_marketplace_unicode_identity as unicode_identity
import v4_global_retrieval_hardening_v3 as retrieval_v3


class FakeResolver:
    _list_payload = staticmethod(retrieval_v3.TCGdexJapaneseProofResolver._list_payload)
    _detail_payload = staticmethod(retrieval_v3.TCGdexJapaneseProofResolver._detail_payload)
    _catalog_card = staticmethod(retrieval_v3.TCGdexJapaneseProofResolver._catalog_card)
    _local_variants = staticmethod(retrieval_v3.TCGdexJapaneseProofResolver._local_variants)

    def __init__(self, *, error_path: str = ""):
        self.error_path = error_path
        self.calls = []

    @staticmethod
    def _card(card_id: str, set_id: str, set_name: str, name: str):
        return {
            "id": card_id,
            "localId": "071",
            "name": name,
            "set": {
                "id": set_id,
                "name": set_name,
                "cardCount": {"official": 66},
            },
        }

    def _get(self, path: str, *, params=None):
        self.calls.append((path, params))
        if path == self.error_path:
            return -1, {}
        if path == "sets":
            return 200, [
                {"id": "SM-A", "cardCount": {"official": 66}},
                {"id": "SM-B", "cardCount": {"official": 66}},
            ]
        if path == "sets/SM-A/071":
            return 200, self._card(
                "SM-A-071", "SM-A", "セットA", "ポケモンだいすきクラブ"
            )
        if path == "sets/SM-B/071":
            return 200, self._card("SM-B-071", "SM-B", "セットB", "別カード")
        if path in {"sets/SM-A/71", "sets/SM-B/71"}:
            return 404, {}
        return 404, {}


class MagiUniqueNameAmongFullNumberTests(unittest.TestCase):
    def _original(self):
        return native.MagiNativeResolution(
            "AMBIGUOUS",
            "target_catalog_unproven:TCGDEX_MULTIPLE_CARDS_FOR_FULL_NUMBER",
        )

    def test_one_exact_japanese_name_disambiguates_multiple_coordinates(self):
        title = "〔PSA10鑑定済〕ポケモンだいすきクラブ【SR】{071/066} 1枚の通販"
        ask = japan.Ask("magi", "https://magi.camp/items/1", title, 100000, title)
        resolver = FakeResolver()
        with mock.patch.object(core, "_norm", unicode_identity._unicode_identity_norm):
            result = unique_name.recover_unique_name_among_full_number_resolution(
                ask,
                self._original(),
                resolver=resolver,
            )
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "SM-A-071")
        self.assertEqual(result.set_id, "SM-A")
        self.assertIsNotNone(result.identity)
        assert result.identity is not None
        self.assertEqual(result.identity.name, "ポケモンだいすきクラブ")
        self.assertEqual(result.identity.number, "71/66")

    def test_two_candidate_names_in_provider_evidence_remain_ambiguous(self):
        title = "PSA10 ポケモンだいすきクラブ 別カード 071/066 1枚"
        ask = japan.Ask("magi", "https://magi.camp/items/2", title, 100000, title)
        original = self._original()
        with mock.patch.object(core, "_norm", unicode_identity._unicode_identity_norm):
            result = unique_name.recover_unique_name_among_full_number_resolution(
                ask,
                original,
                resolver=FakeResolver(),
            )
        self.assertIs(result, original)

    def test_no_candidate_name_in_provider_evidence_remains_ambiguous(self):
        title = "PSA10 未知カード 071/066 1枚"
        ask = japan.Ask("magi", "https://magi.camp/items/3", title, 100000, title)
        original = self._original()
        with mock.patch.object(core, "_norm", unicode_identity._unicode_identity_norm):
            result = unique_name.recover_unique_name_among_full_number_resolution(
                ask,
                original,
                resolver=FakeResolver(),
            )
        self.assertIs(result, original)

    def test_provider_error_during_candidate_universe_fails_closed(self):
        title = "PSA10 ポケモンだいすきクラブ 071/066 1枚"
        ask = japan.Ask("magi", "https://magi.camp/items/4", title, 100000, title)
        original = self._original()
        with mock.patch.object(core, "_norm", unicode_identity._unicode_identity_norm):
            result = unique_name.recover_unique_name_among_full_number_resolution(
                ask,
                original,
                resolver=FakeResolver(error_path="sets/SM-B/071"),
            )
        self.assertIs(result, original)

    def test_unrelated_rejection_is_untouched_without_resolver_reads(self):
        title = "PSA10 ポケモンだいすきクラブ 071/066 1枚"
        ask = japan.Ask("magi", "https://magi.camp/items/5", title, 100000, title)
        original = native.MagiNativeResolution("NO_MATCH", "japanese_set_name_unproven")
        resolver = FakeResolver()
        result = unique_name.recover_unique_name_among_full_number_resolution(
            ask,
            original,
            resolver=resolver,
        )
        self.assertIs(result, original)
        self.assertEqual(resolver.calls, [])


if __name__ == "__main__":
    unittest.main()
