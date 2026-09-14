from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_coordinate_authoritative_name as target
import v4_tcgdex_detailed_variants as detailed
import v4_tcgdex_rainbow_variant_recovery as rainbow
import v4_tcgdex_two_of_three_backport as two_of_three


class CoordinateAuthoritativeNameTests(unittest.TestCase):
    def setUp(self) -> None:
        target._RESULT_CACHE.clear()
        target._NEGATIVE_CACHE.clear()

    def _lot(
        self,
        *,
        name: str = "Palkia",
        number: str = "165",
        card_set: str = "Ultra Prism",
        language: str = "English",
    ) -> watcher.Lot:
        return watcher.Lot(
            url="https://gradedcardcenter.com/item/coordinate-test",
            title=name,
            current_price=100.0,
            source_type="fixed",
            grader="PSA",
            grade="10",
            card_set=card_set,
            card_number=number,
            language=language,
            year=2018,
            listing_text=f"{name} #{number} {card_set} {language} PSA 10",
        )

    def _card(
        self,
        *,
        name: str = "Palkia-GX",
        local_id: str = "165",
        set_id: str = "sm5",
        set_name: str = "Ultra Prism",
        official_count: int = 156,
        variants=None,
        variants_detailed=None,
    ) -> dict:
        if variants is None:
            variants = {
                "normal": False,
                "holo": True,
                "reverse": False,
                "firstEdition": False,
            }
        payload = {
            "id": f"{set_id}-{local_id}",
            "localId": local_id,
            "name": name,
            "set": {
                "id": set_id,
                "name": set_name,
                "cardCount": {"official": official_count, "total": official_count + 20},
            },
            "pricing": {},
            "variants": variants,
        }
        if variants_detailed is not None:
            payload["variants_detailed"] = variants_detailed
        return payload

    def _recover(self, lot: watcher.Lot, card: dict, *, set_id: str = "sm5"):
        with patch.object(two_of_three, "_exact_set_ids", return_value=(set_id,)), patch.object(
            canonical, "_json_get", return_value=(200, card, {})
        ):
            return target._recover_exact_set_coordinate(lot)

    def test_omitted_card_form_is_allowed_only_after_coordinate_proof(self) -> None:
        self.assertTrue(target._coordinate_name_compatible("Palkia", "Palkia-GX"))
        self.assertTrue(target._coordinate_name_compatible("Palkia GX", "Palkia-GX"))
        self.assertTrue(target._coordinate_name_compatible("Palkia Full Art", "Palkia-GX"))
        self.assertTrue(target._coordinate_name_compatible("Palkia GX FA", "Palkia-GX"))

    def test_explicit_conflicting_card_form_is_blocking(self) -> None:
        self.assertFalse(target._coordinate_name_compatible("Palkia V", "Palkia-GX"))
        self.assertFalse(target._coordinate_name_compatible("Palkia V Full Art", "Palkia-GX"))
        self.assertFalse(target._coordinate_name_compatible("Dialga", "Palkia-GX"))

    def test_numerator_only_recovers_exact_set_localid_and_enriches_denominator(self) -> None:
        result = self._recover(self._lot(name="Palkia", number="165"), self._card())
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "sm5-165")
        self.assertEqual(result.local_id, "165")
        self.assertEqual(result.full_number, "165/156")
        self.assertEqual(result.name, "Palkia-GX")

    def test_supplied_denominator_remains_exact(self) -> None:
        self.assertIsNotNone(
            self._recover(self._lot(number="165/156"), self._card())
        )
        self.assertIsNone(
            self._recover(self._lot(number="165/157"), self._card())
        )

    def test_team_rocket_number_can_make_holo_word_redundant(self) -> None:
        lot = self._lot(
            name="Dark Blastoise",
            number="3/82",
            card_set="Team Rocket",
        )
        card = self._card(
            name="Dark Blastoise",
            local_id="3",
            set_id="base5",
            set_name="Team Rocket",
            official_count=82,
            variants={
                "normal": False,
                "holo": True,
                "reverse": False,
                "firstEdition": False,
            },
        )
        result = self._recover(lot, card, set_id="base5")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "EXACT")

    def test_same_coordinate_holo_reverse_without_finish_stays_blocked(self) -> None:
        lot = self._lot(
            name="Dark Blastoise",
            number="4/110",
            card_set="Legendary Collection",
        )
        detailed_variants = [
            {"type": "holo", "size": "standard", "languages": ["en"]},
            {"type": "reverse", "size": "standard", "languages": ["en"]},
        ]
        card = self._card(
            name="Dark Blastoise",
            local_id="4",
            set_id="base6",
            set_name="Legendary Collection",
            official_count=110,
            variants={
                "normal": False,
                "holo": True,
                "reverse": True,
                "firstEdition": False,
            },
            variants_detailed=detailed_variants,
        )
        self.assertIsNone(self._recover(lot, card, set_id="base6"))

    def test_same_coordinate_reverse_is_recovered_when_listing_discriminates_it(self) -> None:
        lot = self._lot(
            name="Dark Blastoise Reverse",
            number="4/110",
            card_set="Legendary Collection",
        )
        detailed_variants = [
            {"type": "holo", "size": "standard", "languages": ["en"]},
            {"type": "reverse", "size": "standard", "languages": ["en"]},
        ]
        card = self._card(
            name="Dark Blastoise",
            local_id="4",
            set_id="base6",
            set_name="Legendary Collection",
            official_count=110,
            variants={
                "normal": False,
                "holo": True,
                "reverse": True,
                "firstEdition": False,
            },
            variants_detailed=detailed_variants,
        )
        result = self._recover(lot, card, set_id="base6")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "EXACT")

    def test_rainbow_descriptor_requires_structured_rainbow_proof(self) -> None:
        rainbow._install_rainbow_dimension_support()
        lot = self._lot(name="Palkia Rainbow", number="165/156")
        rainbow_detail = [
            {
                "type": "holo",
                "size": "standard",
                "foil": "rainbow",
                "languages": ["en"],
            }
        ]
        proven = self._card(variants_detailed=rainbow_detail)
        self.assertIsNotNone(self._recover(lot, proven))

        ordinary = self._card()
        self.assertIsNone(self._recover(lot, ordinary))

    def test_modern_coordinate_does_not_require_an_edition_dimension(self) -> None:
        result = self._recover(self._lot(), self._card())
        self.assertIsNotNone(result)
        # This layer deliberately introduces no blanket First Edition/Unlimited
        # requirement. Existing downstream catalogue-applicability gates remain.
        self.assertNotIn(
            "edition",
            detailed._expected_from_lot(self._lot()),
        )

    def test_non_unique_exact_set_or_materially_wrong_name_never_recovers(self) -> None:
        lot = self._lot()
        with patch.object(two_of_three, "_exact_set_ids", return_value=("sm5", "other")):
            self.assertIsNone(target._recover_exact_set_coordinate(lot))
        self.assertIsNone(self._recover(lot, self._card(name="Dialga-GX")))

    def test_runtime_installer_order_preserves_fail_closed_variant_gates(self) -> None:
        source = Path("run_watcher_multimarket.py").read_text(encoding="utf-8")
        unique_marker = "install_v4_tcgdex_unique_coordinate_fallback()"
        name_filtered_marker = "install_v4_tcgdex_name_filtered_coordinate_recovery()"
        detailed_marker = "install_v4_tcgdex_detailed_variants()"
        rainbow_marker = "install_v4_tcgdex_rainbow_variant_recovery()"
        coordinate_marker = "install_v4_tcgdex_coordinate_authoritative_name()"
        for marker in (
            unique_marker,
            name_filtered_marker,
            detailed_marker,
            rainbow_marker,
            coordinate_marker,
        ):
            self.assertIn(marker, source)
        self.assertGreater(source.index(name_filtered_marker), source.index(unique_marker))
        self.assertGreater(source.index(coordinate_marker), source.index(detailed_marker))
        self.assertGreater(source.index(coordinate_marker), source.index(rainbow_marker))


if __name__ == "__main__":
    unittest.main()
