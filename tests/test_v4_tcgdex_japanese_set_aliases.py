from __future__ import annotations

import unittest
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_generalized_coordinate_recovery as generalized
import v4_tcgdex_japanese_set_aliases as aliases


class JapaneseSetAliasTests(unittest.TestCase):
    def setUp(self):
        self.key = generalized._alias_key("ja", "Night Wanderer")
        self.original_aliases = generalized._SET_ALIASES
        self.original_by_key = dict(generalized._SET_ALIASES_BY_KEY)
        aliases.install_v4_tcgdex_japanese_set_aliases()

    def tearDown(self):
        generalized._SET_ALIASES = self.original_aliases
        generalized._SET_ALIASES_BY_KEY.clear()
        generalized._SET_ALIASES_BY_KEY.update(self.original_by_key)

    def test_night_wanderer_maps_to_official_sv6a_namespace(self):
        alias = generalized._SET_ALIASES_BY_KEY[self.key]
        self.assertEqual(alias.tcgdex_set_id, "SV6a")
        self.assertEqual(alias.tcgdex_official_count, 64)
        self.assertTrue(alias.require_numeric_denominator)
        self.assertTrue(alias.allow_localized_name_mismatch)

    def test_night_wanderer_exact_coordinate_recovers_zorua_from_sv6a(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/night-wanderer-test",
            title="Zorua",
            current_price=25.0,
            source_type="fixed",
            grader="CA",
            grade="9.5",
            card_number="072/064",
            card_set="Night Wanderer",
            language="Japanese",
            body=(
                "Catégorie: Pokémon\n"
                "Référence: #072/064\n"
                "Série: Night Wanderer\n"
                "Langue: Japanese\n"
            ),
        )
        detail = {
            "id": "SV6a-072",
            "localId": "072",
            "name": "ゾロア",
            "set": {
                "id": "SV6a",
                "name": "ナイトワンダラー",
                "cardCount": {"official": 64},
            },
            "variants": {"holo": True},
        }

        def fake_get(url, **kwargs):
            self.assertIn("/ja/sets/SV6a/072", url)
            return 200, {"data": detail}, {}

        with patch.object(canonical, "_json_get", side_effect=fake_get):
            result = generalized._recover_from_set_alias(lot)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "SV6a-072")
        self.assertEqual(result.set_id, "SV6a")
        self.assertEqual(result.set_name, "Night Wanderer")
        self.assertEqual(result.full_number, "072/064")
        self.assertEqual(result.name, "Zorua")
        self.assertEqual(result.language_code, "ja")

    def test_wrong_denominator_does_not_use_alias(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/night-wanderer-wrong-denominator",
            title="Zorua",
            current_price=25.0,
            source_type="fixed",
            card_number="072/063",
            card_set="Night Wanderer",
            language="Japanese",
        )
        with patch.object(
            canonical,
            "_json_get",
            side_effect=AssertionError("wrong denominator must not hit TCGdex"),
        ):
            self.assertIsNone(generalized._recover_from_set_alias(lot))


if __name__ == "__main__":
    unittest.main()
