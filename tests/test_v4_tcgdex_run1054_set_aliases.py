from __future__ import annotations

import unittest

import watcher
import v4_tcgdex_generalized_coordinate_recovery as generalized
import v4_tcgdex_run1054_set_aliases as run1054


class TestV4TCGdexRun1054SetAliases(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        run1054.install_v4_tcgdex_run1054_set_aliases()

    def _lot(
        self,
        *,
        name: str,
        card_set: str,
        number: str,
        language: str,
        year: int,
    ) -> watcher.Lot:
        return watcher.Lot(
            url="https://gradedcardcenter.com/item/run1054-test",
            title=f"PSA 9 {name}",
            current_price=50.0,
            source_type="fixed",
            grader="PSA",
            grade="9",
            card_set=card_set,
            card_number=number,
            language=language,
            year=year,
        )

    def _card(
        self,
        *,
        card_id: str,
        local_id: str,
        name: str,
        set_id: str,
        count: int,
    ) -> dict:
        return {
            "id": card_id,
            "localId": local_id,
            "name": name,
            "set": {
                "id": set_id,
                "name": "localized set",
                "cardCount": {"official": count},
            },
            "pricing": {},
            "variants": {},
        }

    def test_all_seven_run1054_aliases_are_registered(self) -> None:
        cases = (
            ("French", "SWSH Promo", "SWSH207", "swshp", 307, "", False),
            ("Japanese", "VMAX Climax", "200/184", "S8b", 184, "", True),
            ("Japanese", "Mega Dream ex", "204/193", "M2a", 193, "", True),
            ("Japanese", "Scarlet & Violet Promos", "232/SV-P", "SV-P", 0, "SV-P", True),
            ("Japanese", "Ruler of the Black Flame", "111/108", "SV3", 108, "", True),
            ("Japanese", "M-P Promotional cards", "020/M-P", "M-P", 0, "M-P", True),
            ("Japanese", "The Glory of Team Rocket", "109/098", "SV10", 98, "", True),
        )
        for language, card_set, number, set_id, count, suffix, localized in cases:
            with self.subTest(card_set=card_set):
                lot = self._lot(
                    name="Reviewed card",
                    card_set=card_set,
                    number=number,
                    language=language,
                    year=2025,
                )
                language_code, listing_set, reference, _, _, _ = generalized._lot_components(lot)
                alias = generalized._SET_ALIASES_BY_KEY.get(
                    generalized._alias_key(language_code, listing_set)
                )
                self.assertIsNotNone(alias)
                assert alias is not None
                self.assertEqual(alias.tcgdex_set_id, set_id)
                self.assertEqual(alias.tcgdex_official_count, count)
                self.assertEqual(alias.required_reference_suffix, suffix)
                self.assertEqual(alias.allow_localized_name_mismatch, localized)
                self.assertTrue(generalized._validate_reference_for_alias(reference, alias))

    def test_all_seven_run1054_coordinates_pass_exact_coordinate_proof(self) -> None:
        cases = (
            ("Clamiral de Hisui", "SWSH Promo", "SWSH207", "French", 2022, "swshp", 307, "Clamiral de Hisui", False),
            ("Dedenne", "VMAX Climax", "200/184", "Japanese", 2021, "S8b", 184, "デデンネ", True),
            ("Hop's Trevenant", "Mega Dream ex", "204/193", "Japanese", 2025, "M2a", 193, "ホップのオーロット", True),
            ("Iono's Wattrel", "Scarlet & Violet Promos", "232/SV-P", "Japanese", 2025, "SV-P", 0, "ナンジャモのカイデン", True),
            ("Palafin", "Ruler of the Black Flame", "111/108", "Japanese", 2023, "SV3", 108, "イルカマン", True),
            ("Pikachu", "M-P Promotional cards", "020/M-P", "Japanese", 2025, "M-P", 0, "ピカチュウ", True),
            ("Team Rocket's Meowth", "The Glory of Team Rocket", "109/098", "Japanese", 2025, "SV10", 98, "ロケット団のニャース", True),
        )
        for name, card_set, number, language, year, set_id, count, provider_name, localized in cases:
            with self.subTest(name=name):
                lot = self._lot(
                    name=name,
                    card_set=card_set,
                    number=number,
                    language=language,
                    year=year,
                )
                local_id = generalized._reference_candidates(number)[0]
                result = generalized._canonical_from_coordinate(
                    lot,
                    self._card(
                        card_id=f"{set_id}-{local_id}",
                        local_id=local_id,
                        name=provider_name,
                        set_id=set_id,
                        count=count,
                    ),
                    language_code="fr" if language == "French" else "ja",
                    listing_set=card_set,
                    listing_name=name,
                    expected_set_id=set_id,
                    expected_count=count,
                    allow_localized_name_mismatch=localized,
                )
                self.assertIsNotNone(result)
                assert result is not None
                self.assertEqual(result.status, "EXACT")
                self.assertEqual(result.set_id, set_id)
                self.assertEqual(result.reason, "TCGDEX_EXACT_SET_LOCALID")
                self.assertFalse(result.unique_name_number)

    def test_numeric_set_aliases_reject_missing_or_wrong_denominator(self) -> None:
        for card_set, good, bad in (
            ("VMAX Climax", "200/184", "200/185"),
            ("Mega Dream ex", "204/193", "204/194"),
            ("Ruler of the Black Flame", "111/108", "111/109"),
            ("The Glory of Team Rocket", "109/098", "109/099"),
        ):
            with self.subTest(card_set=card_set):
                alias = generalized._SET_ALIASES_BY_KEY[
                    ("ja", generalized._norm_text(card_set))
                ]
                self.assertTrue(generalized._validate_reference_for_alias(good, alias))
                self.assertFalse(generalized._validate_reference_for_alias(bad, alias))
                self.assertFalse(
                    generalized._validate_reference_for_alias(good.split("/")[0], alias)
                )

    def test_japanese_promo_aliases_require_exact_namespace_suffix(self) -> None:
        cases = (
            ("Scarlet & Violet Promos", "232/SV-P", "232/M-P"),
            ("M-P Promotional cards", "020/M-P", "020/SV-P"),
        )
        for card_set, good, bad in cases:
            with self.subTest(card_set=card_set):
                alias = generalized._SET_ALIASES_BY_KEY[
                    ("ja", generalized._norm_text(card_set))
                ]
                self.assertTrue(generalized._validate_reference_for_alias(good, alias))
                self.assertFalse(generalized._validate_reference_for_alias(bad, alias))
                self.assertFalse(
                    generalized._validate_reference_for_alias(good.split("/")[0], alias)
                )

    def test_swsh_promo_alias_keeps_same_language_name_gate(self) -> None:
        lot = self._lot(
            name="Clamiral de Hisui",
            card_set="SWSH Promo",
            number="SWSH207",
            language="French",
            year=2022,
        )
        good = self._card(
            card_id="swshp-SWSH207",
            local_id="SWSH207",
            name="Clamiral de Hisui",
            set_id="swshp",
            count=307,
        )
        kwargs = dict(
            language_code="fr",
            listing_set="SWSH Promo",
            listing_name="Clamiral de Hisui",
            expected_set_id="swshp",
            expected_count=307,
            allow_localized_name_mismatch=False,
        )
        self.assertIsNotNone(generalized._canonical_from_coordinate(lot, good, **kwargs))
        self.assertIsNone(
            generalized._canonical_from_coordinate(
                lot,
                {**good, "name": "Pikachu"},
                **kwargs,
            )
        )
        self.assertIsNone(
            generalized._canonical_from_coordinate(
                lot,
                {**good, "localId": "SWSH208"},
                **kwargs,
            )
        )

    def test_registration_conflict_fails_closed(self) -> None:
        alias = run1054._ALIASES[0]
        key = generalized._alias_key(alias.language_code, alias.listing_set)
        original = generalized._SET_ALIASES_BY_KEY[key]
        generalized._SET_ALIASES_BY_KEY[key] = generalized.ExactSetAlias(
            "fr", "SWSH Promo", "wrong", 307
        )
        try:
            with self.assertRaises(RuntimeError):
                run1054.install_v4_tcgdex_run1054_set_aliases()
        finally:
            generalized._SET_ALIASES_BY_KEY[key] = original


if __name__ == "__main__":
    unittest.main()
