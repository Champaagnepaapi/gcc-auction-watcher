from __future__ import annotations

import unittest
from unittest import mock

import japan_edge_hunter as japan
import v4_global_market_core as core
import v4_global_marketplace_magi_native_identity as native
import v4_global_marketplace_magi_set_name_rarity_unique_card as rarity_unique
import v4_global_marketplace_unicode_identity as unicode_identity


TITLE = "PSA10 ポケモンカード ゲンガー R ダークファンタズマ 1枚の通販"
SIGHTSEER_SR = "かんこうきゃく SR PSA10 ポケモンカード 1枚の通販"
SIGHTSEER_TR = "PSA10 ポケモンカード かんこうきゃく TR 1枚の通販"


class FakeResolver:
    def __init__(self, *, second_rarity="Character Rare", error_path="", global_duplicate=False):
        self.calls = []
        self.second_rarity = second_rarity
        self.error_path = error_path
        self.global_duplicate = global_duplicate

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
        if path == "cards" and params == {"name": "eq:かんこうきゃく"}:
            rows = [
                {"id": "SM7a-056", "localId": "056", "name": "かんこうきゃく"},
                {"id": "SM12a-149", "localId": "149", "name": "かんこうきゃく"},
                {"id": "SM12a-192", "localId": "192", "name": "かんこうきゃく"},
            ]
            if self.global_duplicate:
                rows.append({"id": "TEST-999", "localId": "999", "name": "かんこうきゃく"})
            return 200, rows
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
        if path == "cards/SM7a-056":
            return 200, {
                "id": "SM7a-056",
                "localId": "056",
                "name": "かんこうきゃく",
                "rarity": "Common",
                "set": {
                    "id": "SM7a",
                    "name": "迅雷スパーク",
                    "cardCount": {"official": 60},
                },
            }
        if path == "cards/SM12a-149":
            return 200, {
                "id": "SM12a-149",
                "localId": "149",
                "name": "かんこうきゃく",
                "rarity": None,
                "set": {
                    "id": "SM12a",
                    "name": "TAG TEAM GX タッグオールスターズ",
                    "cardCount": {"official": 173},
                },
            }
        if path == "cards/SM12a-192":
            return 200, {
                "id": "SM12a-192",
                "localId": "192",
                "name": "かんこうきゃく",
                "rarity": "Ultra Rare",
                "set": {
                    "id": "SM12a",
                    "name": "TAG TEAM GX タッグオールスターズ",
                    "cardCount": {"official": 173},
                },
            }
        if path == "cards/TEST-999":
            return 200, {
                "id": "TEST-999",
                "localId": "999",
                "name": "かんこうきゃく",
                "rarity": "Ultra Rare",
                "set": {
                    "id": "TEST",
                    "name": "テストセット",
                    "cardCount": {"official": 999},
                },
            }
        raise AssertionError((path, params))

    @staticmethod
    def _detail_payload(payload):
        return payload

    @staticmethod
    def _list_payload(payload):
        return payload if isinstance(payload, list) else []


class MagiSetNameRarityUniqueCardTests(unittest.TestCase):
    def _original(self):
        return native.MagiNativeResolution(
            "AMBIGUOUS",
            "target_catalog_unproven:TCGDEX_SET_NAME_CARD_NAME_AMBIGUOUS",
        )

    def _missing_set(self):
        return native.MagiNativeResolution("NO_MATCH", "japanese_set_name_unproven")

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

    def test_sightseer_sr_recovers_globally_unique_exact_name_and_rarity(self):
        resolver = FakeResolver()
        ask = japan.Ask("magi", "https://magi.camp/items/1506971104", SIGHTSEER_SR, 50000, SIGHTSEER_SR)
        with mock.patch.object(core, "_norm", unicode_identity._unicode_identity_norm):
            result = rarity_unique.recover_set_name_rarity_unique_card_resolution(
                ask,
                self._missing_set(),
                resolver=resolver,
            )
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "SM12a-192")
        self.assertEqual(result.set_id, "SM12a")
        self.assertIsNotNone(result.identity)
        assert result.identity is not None
        self.assertEqual(result.identity.name, "かんこうきゃく")
        self.assertEqual(result.identity.set_name, "TAG TEAM GX タッグオールスターズ")
        self.assertEqual(result.identity.number, "192/173")
        self.assertIn("magi_rarity_exact:SR", result.reason)
        self.assertEqual(resolver.calls[0], ("cards", {"name": "eq:かんこうきゃく"}))

    def test_sightseer_tr_stays_blocked_without_network(self):
        resolver = FakeResolver()
        original = self._missing_set()
        result = rarity_unique.recover_set_name_rarity_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/1238824877", SIGHTSEER_TR, 50000, SIGHTSEER_TR),
            original,
            resolver=resolver,
        )
        self.assertIs(result, original)
        self.assertEqual(resolver.calls, [])

    def test_two_global_sr_candidates_stay_ambiguous(self):
        resolver = FakeResolver(global_duplicate=True)
        result = rarity_unique.recover_set_name_rarity_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/7", SIGHTSEER_SR, 50000, SIGHTSEER_SR),
            self._missing_set(),
            resolver=resolver,
        )
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertIn("GLOBAL_NAME_RARITY_CARD_AMBIGUOUS", result.reason)

    def test_global_candidate_detail_error_fails_closed(self):
        resolver = FakeResolver(error_path="cards/SM12a-192")
        result = rarity_unique.recover_set_name_rarity_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/8", SIGHTSEER_SR, 50000, SIGHTSEER_SR),
            self._missing_set(),
            resolver=resolver,
        )
        self.assertNotEqual(result.status, "EXACT")
        self.assertIn("HTTP_-1", result.reason)

    def test_missing_set_name_must_be_immediately_before_rarity(self):
        title = "かんこうきゃく ポケモンカード SR PSA10 1枚の通販"
        resolver = FakeResolver()
        original = self._missing_set()
        result = rarity_unique.recover_set_name_rarity_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/9", title, 50000, title),
            original,
            resolver=resolver,
        )
        self.assertIs(result, original)
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
        original = native.MagiNativeResolution("NO_MATCH", "collector_number_unproven")
        result = rarity_unique.recover_set_name_rarity_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/6", TITLE, 50000, TITLE),
            original,
            resolver=resolver,
        )
        self.assertIs(result, original)
        self.assertEqual(resolver.calls, [])


if __name__ == "__main__":
    unittest.main()
