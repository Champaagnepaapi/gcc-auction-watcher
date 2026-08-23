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
    def __init__(self, *, cards=None, detail_name="ストライク"):
        self.calls = []
        self.cards = cards if cards is not None else [
            {"id": "PMCG2-017", "localId": "017", "name": "ストライク"}
        ]
        self.detail_name = detail_name

    def _get(self, path, *, params=None):
        self.calls.append((path, params))
        if path.startswith("sets/"):
            return 200, {
                "id": "PMCG2",
                "name": "ポケモンジャングル",
                "cardCount": {"official": 48, "total": 48},
                "cards": self.cards,
            }
        if path == "cards/PMCG2-017":
            return 200, {
                "id": "PMCG2-017",
                "localId": "017",
                "name": self.detail_name,
                "set": {
                    "id": "PMCG2",
                    "name": "ポケモンジャングル",
                    "cardCount": {"official": 48, "total": 48},
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
        self.assertEqual(len(resolver.calls), 2)

    def test_name_only_listing_never_runs_catalog_fallback(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/2",
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
        self.assertEqual(resolver.calls, [])

    def test_two_card_names_in_same_set_are_ambiguous(self):
        title = "【PSA10】 ストライク ピカチュウ [旧裏第2弾/ポケモンジャングル] 1枚の通販"
        resolver = FakeResolver(cards=[
            {"id": "PMCG2-017", "localId": "017", "name": "ストライク"},
            {"id": "PMCG2-025", "localId": "025", "name": "ピカチュウ"},
        ])
        result = set_unique.recover_set_name_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/3", title, 50000, title),
            native.MagiNativeResolution("NO_MATCH", "collector_number_unproven"),
            resolver=resolver,
        )
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertIn("CARD_NAME_AMBIGUOUS", result.reason)
        self.assertEqual(len(resolver.calls), 1)

    def test_detail_name_conflict_fails_closed(self):
        resolver = FakeResolver(detail_name="別のカード")
        result = set_unique.recover_set_name_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/4", SCYTHER, 50000, SCYTHER),
            native.MagiNativeResolution("NO_MATCH", "collector_number_unproven"),
            resolver=resolver,
        )
        self.assertEqual(result.status, "NO_MATCH")
        self.assertIn("CARD_DETAIL_CONFLICT", result.reason)

    def test_other_rejection_reason_is_untouched(self):
        resolver = FakeResolver()
        original = native.MagiNativeResolution("NO_MATCH", "set_code_unproven")
        result = set_unique.recover_set_name_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/5", SCYTHER, 50000, SCYTHER),
            original,
            resolver=resolver,
        )
        self.assertIs(result, original)
        self.assertEqual(resolver.calls, [])


if __name__ == "__main__":
    unittest.main()
