from __future__ import annotations

import unittest
from unittest import mock

import japan_edge_hunter as japan
import v4_global_market_core as core
import v4_global_marketplace_magi_native_identity as native
import v4_global_marketplace_magi_set_name_rarity_unique_card as rarity_unique
import v4_global_marketplace_unicode_identity as unicode_identity


TITLE = "PSA10 ポケモンカード ゲンガー R ダークファンタズマ 1枚の通販"


class FakeResolver:
    def __init__(self, *, second_rarity="Character Rare", error_path=""):
        self.calls = []
        self.second_rarity = second_rarity
        self.error_path = error_path

    def _get(self, path, *, params=None):
        self.calls.append((path, params))
        if path == self.error_path:
            return -1, {}
        if path == "sets":
            return 200, [
                {"id": "S10a", "name": "ダークファンタズマ"},
                {"id": "SV2a", "name": "ポケモンカード151"},
            ]
        if path == "sets/S10a":
            return 200, {
                "id": "S10a",
                "name": "ダークファンタズマ",
                "cardCount": {"official": 71},
                "cards": [
                    {"id": "S10a-023", "localId": "023", "name": "ゲンガー"},
                    {"id": "S10a-074", "localId": "074", "name": "ゲンガー"},
                ],
            }
        if path == "cards/S10a-023":
            return 200, {
                "id": "S10a-023",
                "localId": "023",
                "name": "ゲンガー",
                "rarity": "Rare",
                "set": {"id": "S10a", "name": "ダークファンタズマ"},
            }
        if path == "cards/S10a-074":
            return 200, {
                "id": "S10a-074",
                "localId": "074",
                "name": "ゲンガー",
                "rarity": self.second_rarity,
                "set": {"id": "S10a", "name": "ダークファンタズマ"},
            }
        raise AssertionError(path)

    @staticmethod
    def _detail_payload(payload):
        return payload


class MagiSetNameRarityUniqueCardTests(unittest.TestCase):
    def _original(self):
        return native.MagiNativeResolution(
            "AMBIGUOUS",
            "target_catalog_unproven:TCGDEX_SET_NAME_CARD_NAME_AMBIGUOUS",
        )

    def test_standalone_r_selects_only_exact_rare_same_name_card(self):
        resolver = FakeResolver()
        ask = japan.Ask("magi", "https://magi.camp/items/1", TITLE, 50000, TITLE)
        with mock.patch.object(core, "_norm", unicode_identity._unicode_identity_norm):
            result = rarity_unique.recover_set_name_rarity_unique_card_resolution(
                ask,
                self._original(),
                resolver=resolver,
            )
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "S10a-023")
        self.assertEqual(result.set_id, "S10a")
        self.assertIsNotNone(result.identity)
        assert result.identity is not None
        self.assertEqual(result.identity.name, "ゲンガー")
        self.assertEqual(result.identity.set_name, "ダークファンタズマ")
        self.assertEqual(result.identity.number, "023/71")
        self.assertIn("magi_rarity_exact:R", result.reason)

    def test_unreviewed_sr_mapping_remains_blocked_without_network(self):
        title = TITLE.replace(" R ", " SR ")
        resolver = FakeResolver()
        result = rarity_unique.recover_set_name_rarity_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/2", title, 50000, title),
            self._original(),
            resolver=resolver,
        )
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(result.reason, "magi_rarity_mapping_unreviewed")
        self.assertEqual(resolver.calls, [])

    def test_multiple_distinct_rarity_tokens_remain_ambiguous(self):
        title = TITLE.replace(" R ", " R SR ")
        resolver = FakeResolver()
        result = rarity_unique.recover_set_name_rarity_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/3", title, 50000, title),
            self._original(),
            resolver=resolver,
        )
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(result.reason, "magi_rarity_ambiguous")
        self.assertEqual(resolver.calls, [])

    def test_two_rare_candidates_stay_ambiguous(self):
        resolver = FakeResolver(second_rarity="Rare")
        result = rarity_unique.recover_set_name_rarity_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/4", TITLE, 50000, TITLE),
            self._original(),
            resolver=resolver,
        )
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertIn("RARITY_CARD_AMBIGUOUS", result.reason)

    def test_candidate_detail_error_fails_closed(self):
        resolver = FakeResolver(error_path="cards/S10a-074")
        result = rarity_unique.recover_set_name_rarity_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/5", TITLE, 50000, TITLE),
            self._original(),
            resolver=resolver,
        )
        self.assertNotEqual(result.status, "EXACT")
        self.assertIn("HTTP_-1", result.reason)

    def test_unrelated_rejection_is_untouched_without_network(self):
        resolver = FakeResolver()
        original = native.MagiNativeResolution("NO_MATCH", "japanese_set_name_unproven")
        result = rarity_unique.recover_set_name_rarity_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/6", TITLE, 50000, TITLE),
            original,
            resolver=resolver,
        )
        self.assertIs(result, original)
        self.assertEqual(resolver.calls, [])


if __name__ == "__main__":
    unittest.main()
