from __future__ import annotations

import unittest
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_generalized_coordinate_recovery as generalized
import v4_tcgdex_japanese_set_aliases as aliases


class JapaneseSetAliasTests(unittest.TestCase):
    def setUp(self):
        self.original_aliases = generalized._SET_ALIASES
        self.original_by_key = dict(generalized._SET_ALIASES_BY_KEY)
        aliases.install_v4_tcgdex_japanese_set_aliases()

    def tearDown(self):
        generalized._SET_ALIASES = self.original_aliases
        generalized._SET_ALIASES_BY_KEY.clear()
        generalized._SET_ALIASES_BY_KEY.update(self.original_by_key)

    def _alias(self, listing_set: str):
        return generalized._SET_ALIASES_BY_KEY[
            generalized._alias_key("ja", listing_set)
        ]

    def _lot(self, *, name: str, reference: str, series: str) -> watcher.Lot:
        return watcher.Lot(
            url="https://gradedcardcenter.com/item/japanese-alias-test",
            title=name,
            current_price=25.0,
            source_type="fixed",
            grader="PSA",
            grade="10",
            card_number=reference,
            card_set=series,
            language="Japanese",
            body=(
                "Catégorie: Pokémon\n"
                f"Référence: #{reference}\n"
                f"Série: {series}\n"
                "Langue: Japanese\n"
            ),
        )

    def test_source_pinned_alias_registry_contains_live_gap_sets(self):
        night = self._alias("Night Wanderer")
        rocket = self._alias("Glory of the Team Rocket")
        inferno = self._alias("Inferno X")
        sp = self._alias("S-P Promotional")
        svp = self._alias("SV-P Promos")

        self.assertEqual((night.tcgdex_set_id, night.tcgdex_official_count), ("SV6a", 64))
        self.assertEqual((rocket.tcgdex_set_id, rocket.tcgdex_official_count), ("SV10", 98))
        self.assertEqual((inferno.tcgdex_set_id, inferno.tcgdex_official_count), ("M2", 80))
        self.assertTrue(inferno.require_numeric_denominator)
        self.assertEqual((sp.tcgdex_set_id, sp.required_reference_suffix), ("S-P", "S-P"))
        self.assertEqual((svp.tcgdex_set_id, svp.required_reference_suffix), ("SV-P", "SV-P"))
        self.assertTrue(sp.allow_localized_name_mismatch)
        self.assertTrue(svp.allow_localized_name_mismatch)

    def test_night_wanderer_exact_coordinate_recovers_zorua_from_sv6a(self):
        lot = self._lot(name="Zorua", reference="072/064", series="Night Wanderer")
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

    def test_inferno_x_exact_coordinate_recovers_oricorio(self):
        lot = self._lot(name="Oricorio Ex", reference="111/080", series="Inferno X")
        detail = {
            "id": "M2-111",
            "localId": "111",
            "name": "オドリドリex",
            "set": {
                "id": "M2",
                "name": "インフェルノX",
                "cardCount": {"official": 80},
            },
            "variants": {"holo": True},
        }

        def fake_get(url, **kwargs):
            self.assertIn("/ja/sets/M2/111", url)
            return 200, {"data": detail}, {}

        with patch.object(canonical, "_json_get", side_effect=fake_get):
            result = generalized._recover_from_set_alias(lot)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "M2-111")
        self.assertEqual(result.set_id, "M2")
        self.assertEqual(result.name, "Oricorio Ex")

    def test_s_p_promotional_exact_namespace_recovers_mischievous_pichu(self):
        lot = self._lot(
            name="Mischievous Pichu",
            reference="214/S-P",
            series="S-P Promotional",
        )
        detail = {
            "id": "S-P-214",
            "localId": "214",
            "name": "いたずら好きのピチュー",
            "set": {"id": "S-P", "name": "S-P", "cardCount": {"official": 0}},
            "variants": {"holo": True},
        }

        def fake_get(url, **kwargs):
            self.assertIn("/ja/sets/S-P/214", url)
            return 200, {"data": detail}, {}

        with patch.object(canonical, "_json_get", side_effect=fake_get):
            result = generalized._recover_from_set_alias(lot)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "S-P-214")
        self.assertEqual(result.set_id, "S-P")

    def test_sv_p_promos_exact_namespace_recovers_pikachu_coordinates(self):
        for reference in ("001/SV-P", "242/SV-P"):
            with self.subTest(reference=reference):
                local_id = reference.split("/", 1)[0]
                lot = self._lot(name="Pikachu", reference=reference, series="SV-P Promos")
                detail = {
                    "id": f"SV-P-{local_id}",
                    "localId": local_id,
                    "name": "ピカチュウ",
                    "set": {
                        "id": "SV-P",
                        "name": "スカーレット&バイオレット プロモカード",
                        "cardCount": {"official": 0},
                    },
                    "variants": {"holo": True},
                }

                def fake_get(url, **kwargs):
                    self.assertIn(f"/ja/sets/SV-P/{local_id}", url)
                    return 200, {"data": detail}, {}

                with patch.object(canonical, "_json_get", side_effect=fake_get):
                    result = generalized._recover_from_set_alias(lot)

                self.assertIsNotNone(result)
                assert result is not None
                self.assertEqual(result.status, "EXACT")
                self.assertEqual(result.card_id, f"SV-P-{local_id}")
                self.assertEqual(result.set_id, "SV-P")

    def test_wrong_denominator_does_not_use_alias(self):
        lot = self._lot(name="Zorua", reference="072/063", series="Night Wanderer")
        with patch.object(
            canonical,
            "_json_get",
            side_effect=AssertionError("wrong denominator must not hit TCGdex"),
        ):
            self.assertIsNone(generalized._recover_from_set_alias(lot))

    def test_wrong_promo_namespace_does_not_use_alias(self):
        lot = self._lot(
            name="Mischievous Pichu",
            reference="214/XYZ",
            series="S-P Promotional",
        )
        with patch.object(
            canonical,
            "_json_get",
            side_effect=AssertionError("wrong namespace must not hit TCGdex"),
        ):
            self.assertIsNone(generalized._recover_from_set_alias(lot))


if __name__ == "__main__":
    unittest.main()
