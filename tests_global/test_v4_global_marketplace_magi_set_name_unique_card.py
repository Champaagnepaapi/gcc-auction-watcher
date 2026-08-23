from __future__ import annotations

import unittest
from unittest import mock

import japan_edge_hunter as japan
import v4_global_market_core as core
import v4_global_marketplace_magi_native_identity as native
import v4_global_marketplace_magi_set_name_unique_card as set_unique
import v4_global_marketplace_unicode_identity as unicode_identity


SCYTHER = "【PSA10】 ストライク [旧裏第2弾/ポケモンジャングル] [旧裏] 1枚の通販"


class FakeResolver:
    def __init__(
        self,
        *,
        set_id="PMCG2",
        set_name="ポケモンジャングル",
        official_count=48,
        cards=None,
        detail_name="ストライク",
        set_catalog=None,
        detail_set_id=None,
    ):
        self.calls = []
        self.set_id = set_id
        self.set_name = set_name
        self.official_count = official_count
        self.cards = cards if cards is not None else [
            {"id": f"{set_id}-017", "localId": "017", "name": "ストライク"}
        ]
        self.detail_name = detail_name
        self.set_catalog = set_catalog if set_catalog is not None else [
            {"id": set_id, "name": set_name}
        ]
        self.detail_set_id = detail_set_id or set_id

    def _get(self, path, *, params=None):
        self.calls.append((path, params))
        if path == "sets":
            return 200, self.set_catalog
        if path.startswith("sets/"):
            return 200, {
                "id": self.detail_set_id,
                "name": self.set_name,
                "cardCount": {"official": self.official_count, "total": self.official_count},
                "cards": self.cards,
            }
        if path.startswith("cards/"):
            card_id = path.split("/", 1)[1]
            brief = next((row for row in self.cards if row.get("id") == card_id), None)
            if brief is None:
                raise AssertionError(path)
            return 200, {
                "id": card_id,
                "localId": brief["localId"],
                "name": self.detail_name,
                "set": {
                    "id": self.detail_set_id,
                    "name": self.set_name,
                    "cardCount": {"official": self.official_count, "total": self.official_count},
                },
            }
        raise AssertionError(path)

    @staticmethod
    def _detail_payload(payload):
        return payload


class MagiSetNameUniqueCardTests(unittest.TestCase):
    def test_exact_set_name_plus_unique_japanese_card_derives_catalog_coordinate(self):
        ask = japan.Ask("magi", "https://magi.camp/items/1", SCYTHER, 50000, SCYTHER)
        resolver = FakeResolver()
        with mock.patch.object(core, "_norm", unicode_identity._unicode_identity_norm):
            result = set_unique.recover_set_name_unique_card_resolution(
                ask,
                native.MagiNativeResolution("NO_MATCH", "collector_number_unproven"),
                resolver=resolver,
            )
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.identity.name, "ストライク")
        self.assertEqual(result.identity.set_name, "ポケモンジャングル")
        self.assertEqual(result.identity.number, "017/48")
        self.assertEqual(result.card_id, "PMCG2-017")
        self.assertIn("DERIVED_COORDINATE", result.reason)
        # Explicit bracket proof keeps the existing direct exact-set path.
        self.assertEqual([call[0] for call in resolver.calls], ["sets/ポケモンジャングル", "cards/PMCG2-017"])

    def test_literal_catalog_set_name_in_title_derives_coordinate(self):
        title = "【PSA10】ポケモンカード ゲンガー R ダークファンタズマ 1枚の通販"
        resolver = FakeResolver(
            set_id="S10a",
            set_name="ダークファンタズマ",
            official_count=71,
            cards=[{"id": "S10a-023", "localId": "023", "name": "ゲンガー"}],
            detail_name="ゲンガー",
            set_catalog=[
                {"id": "S10a", "name": "ダークファンタズマ"},
                {"id": "SV2a", "name": "ポケモンカード151"},
            ],
        )
        with mock.patch.object(core, "_norm", unicode_identity._unicode_identity_norm):
            result = set_unique.recover_set_name_unique_card_resolution(
                japan.Ask("magi", "https://magi.camp/items/2", title, 50000, title),
                native.MagiNativeResolution("NO_MATCH", "collector_number_unproven"),
                resolver=resolver,
            )
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.identity.name, "ゲンガー")
        self.assertEqual(result.identity.set_name, "ダークファンタズマ")
        self.assertEqual(result.identity.number, "023/71")
        self.assertEqual([call[0] for call in resolver.calls], ["sets", "sets/S10a", "cards/S10a-023"])

    def test_name_only_listing_checks_catalog_but_never_infers_a_set(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/3",
            "かんこうきゃく SR PSA10 ポケモンカード 1枚の通販",
            50000,
            "",
        )
        resolver = FakeResolver()
        result = set_unique.recover_set_name_unique_card_resolution(
            ask,
            native.MagiNativeResolution("NO_MATCH", "collector_number_unproven"),
            resolver=resolver,
        )
        self.assertEqual(result.status, "NO_MATCH")
        self.assertEqual(result.reason, "japanese_set_name_unproven")
        self.assertEqual([call[0] for call in resolver.calls], ["sets"])

    def test_multiple_literal_catalog_sets_in_title_are_ambiguous(self):
        title = "PSA10 ゲンガー ダークファンタズマ ポケモンジャングル 1枚の通販"
        resolver = FakeResolver(set_catalog=[
            {"id": "S10a", "name": "ダークファンタズマ"},
            {"id": "PMCG2", "name": "ポケモンジャングル"},
        ])
        result = set_unique.recover_set_name_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/4", title, 50000, title),
            native.MagiNativeResolution("NO_MATCH", "collector_number_unproven"),
            resolver=resolver,
        )
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(result.reason, "japanese_set_name_ambiguous")
        self.assertEqual([call[0] for call in resolver.calls], ["sets"])

    def test_discovered_set_id_conflict_fails_closed(self):
        title = "PSA10 ゲンガー ダークファンタズマ 1枚の通販"
        resolver = FakeResolver(
            set_id="S10a",
            set_name="ダークファンタズマ",
            official_count=71,
            cards=[{"id": "S10a-023", "localId": "023", "name": "ゲンガー"}],
            detail_name="ゲンガー",
            set_catalog=[{"id": "S10a", "name": "ダークファンタズマ"}],
            detail_set_id="WRONG",
        )
        result = set_unique.recover_set_name_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/5", title, 50000, title),
            native.MagiNativeResolution("NO_MATCH", "collector_number_unproven"),
            resolver=resolver,
        )
        self.assertEqual(result.status, "NO_MATCH")
        self.assertIn("SET_ID_CONFLICT", result.reason)
        self.assertEqual([call[0] for call in resolver.calls], ["sets", "sets/S10a"])

    def test_two_card_names_in_same_set_are_ambiguous(self):
        title = "【PSA10】 ストライク ピカチュウ [旧裏第2弾/ポケモンジャングル] 1枚の通販"
        resolver = FakeResolver(cards=[
            {"id": "PMCG2-017", "localId": "017", "name": "ストライク"},
            {"id": "PMCG2-025", "localId": "025", "name": "ピカチュウ"},
        ])
        result = set_unique.recover_set_name_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/6", title, 50000, title),
            native.MagiNativeResolution("NO_MATCH", "collector_number_unproven"),
            resolver=resolver,
        )
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertIn("CARD_NAME_AMBIGUOUS", result.reason)
        self.assertEqual(len(resolver.calls), 1)

    def test_detail_name_conflict_fails_closed(self):
        resolver = FakeResolver(detail_name="別のカード")
        result = set_unique.recover_set_name_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/7", SCYTHER, 50000, SCYTHER),
            native.MagiNativeResolution("NO_MATCH", "collector_number_unproven"),
            resolver=resolver,
        )
        self.assertEqual(result.status, "NO_MATCH")
        self.assertIn("CARD_DETAIL_CONFLICT", result.reason)

    def test_other_rejection_reason_is_untouched(self):
        resolver = FakeResolver()
        original = native.MagiNativeResolution("NO_MATCH", "set_code_unproven")
        result = set_unique.recover_set_name_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/8", SCYTHER, 50000, SCYTHER),
            original,
            resolver=resolver,
        )
        self.assertIs(result, original)
        self.assertEqual(resolver.calls, [])


if __name__ == "__main__":
    unittest.main()
