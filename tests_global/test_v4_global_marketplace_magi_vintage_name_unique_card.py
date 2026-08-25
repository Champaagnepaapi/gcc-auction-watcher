from __future__ import annotations

import unittest
from unittest import mock

import japan_edge_hunter as japan
import v4_global_market_core as core
import v4_global_marketplace_magi_native_identity as native
import v4_global_marketplace_magi_vintage_name_unique_card as vintage
import v4_global_marketplace_unicode_identity as unicode_identity


HORSEA = "【PSA10】カスミのタッツー LV.16 旧裏 No.116 ポケモンカード 1枚の通販"


class FakeResolver:
    def __init__(self, *, duplicate=False, dex_id=116, error_path=""):
        self.calls = []
        self.duplicate = duplicate
        self.dex_id = dex_id
        self.error_path = error_path

    def _get(self, path, *, params=None):
        self.calls.append((path, params))
        if path == self.error_path:
            return -1, {}
        if path == "cards" and params == {"name": "eq:カスミのタッツー"}:
            rows = [
                {"id": "PMCG5-024", "localId": "024", "name": "カスミのタッツー"},
            ]
            if self.duplicate:
                rows.append(
                    {"id": "TEST-024", "localId": "024", "name": "カスミのタッツー"}
                )
            return 200, rows
        if path == "cards/PMCG5-024":
            return 200, {
                "id": "PMCG5-024",
                "localId": "024",
                "name": "カスミのタッツー",
                "category": "Pokemon",
                "dexId": [self.dex_id],
                "set": {
                    "id": "PMCG5",
                    "name": "リーダーズスタジアム",
                    "cardCount": {"official": 96},
                },
            }
        raise AssertionError((path, params))

    @staticmethod
    def _list_payload(payload):
        return payload if isinstance(payload, list) else []

    @staticmethod
    def _detail_payload(payload):
        return payload


class MagiVintageNameUniqueCardTests(unittest.TestCase):
    def _original(self):
        return native.MagiNativeResolution("NO_MATCH", "japanese_set_name_unproven")

    def test_horsea_exact_name_and_printed_dex_recovers_coordinate(self):
        resolver = FakeResolver()
        ask = japan.Ask("magi", "https://magi.camp/items/1615913324", HORSEA, 50000, HORSEA)
        with mock.patch.object(core, "_norm", unicode_identity._unicode_identity_norm):
            result = vintage.recover_vintage_name_unique_card_resolution(
                ask,
                self._original(),
                resolver=resolver,
            )
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "PMCG5-024")
        self.assertEqual(result.set_id, "PMCG5")
        self.assertIsNotNone(result.identity)
        assert result.identity is not None
        self.assertEqual(result.identity.name, "カスミのタッツー")
        self.assertEqual(result.identity.set_name, "リーダーズスタジアム")
        self.assertEqual(result.identity.number, "024/96")
        self.assertEqual(
            resolver.calls,
            [
                ("cards", {"name": "eq:カスミのタッツー"}),
                ("cards/PMCG5-024", None),
            ],
        )

    def test_duplicate_global_name_stays_ambiguous_without_detail(self):
        resolver = FakeResolver(duplicate=True)
        result = vintage.recover_vintage_name_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/2", HORSEA, 50000, HORSEA),
            self._original(),
            resolver=resolver,
        )
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertIn("GLOBAL_EXACT_NAME_AMBIGUOUS", result.reason)
        self.assertEqual(len(resolver.calls), 1)

    def test_printed_dex_conflict_blocks(self):
        resolver = FakeResolver(dex_id=117)
        result = vintage.recover_vintage_name_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/3", HORSEA, 50000, HORSEA),
            self._original(),
            resolver=resolver,
        )
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertIn("PRINTED_DEX_NUMBER_CONFLICT", result.reason)

    def test_missing_lv_marker_does_not_spend_network(self):
        title = HORSEA.replace(" LV.16", "")
        resolver = FakeResolver()
        original = self._original()
        result = vintage.recover_vintage_name_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/4", title, 50000, title),
            original,
            resolver=resolver,
        )
        self.assertIs(result, original)
        self.assertEqual(resolver.calls, [])

    def test_unrelated_reason_is_untouched(self):
        resolver = FakeResolver()
        original = native.MagiNativeResolution("AMBIGUOUS", "collector_number_ambiguous")
        result = vintage.recover_vintage_name_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/5", HORSEA, 50000, HORSEA),
            original,
            resolver=resolver,
        )
        self.assertIs(result, original)
        self.assertEqual(resolver.calls, [])

    def test_provider_error_is_not_clean_negative(self):
        resolver = FakeResolver(error_path="cards/PMCG5-024")
        result = vintage.recover_vintage_name_unique_card_resolution(
            japan.Ask("magi", "https://magi.camp/items/6", HORSEA, 50000, HORSEA),
            self._original(),
            resolver=resolver,
        )
        self.assertEqual(result.status, "ERROR")
        self.assertIn("HTTP_-1", result.reason)


if __name__ == "__main__":
    unittest.main()
