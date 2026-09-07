from __future__ import annotations

import unittest
from unittest import mock

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_name_filtered_coordinate_recovery as recovery
import v4_tcgdex_unique_coordinate_fallback as unique


class TcgdexNameFilteredCoordinateRecoveryTests(unittest.TestCase):
    @staticmethod
    def _lot() -> watcher.Lot:
        return watcher.Lot(
            url="https://gradedcardcenter.com/item/magneti",
            title="PSA 9 Magneti",
            current_price=50.0,
            source_type="fixed",
            grader="PSA",
            grade="9",
            card_set="Set de base",
            card_number="#53/102",
            language="French",
            year=1999,
        )

    def test_possessive_punctuation_is_equivalent(self):
        self.assertTrue(
            recovery._approximate_name_equivalent(
                "Brock Ninetales", "Brock’s Ninetales"
            )
        )
        self.assertTrue(
            recovery._approximate_name_equivalent(
                "Brock Ninetales", "Brock's Ninetales"
            )
        )

    def test_small_typo_is_equivalent_after_exact_coordinate_anchor(self):
        self.assertTrue(
            recovery._approximate_name_equivalent(
                "Brock Ninetales", "Brock Ninetalez"
            )
        )
        self.assertTrue(
            recovery._approximate_name_equivalent("Pikachu", "Pikachh")
        )

    def test_material_name_change_is_not_equivalent(self):
        self.assertFalse(
            recovery._approximate_name_equivalent(
                "Brock Ninetales", "Brock Rhydon"
            )
        )
        self.assertFalse(
            recovery._approximate_name_equivalent("Pikachu", "Raichu")
        )

    def test_numeric_name_tokens_must_match_exactly(self):
        self.assertFalse(
            recovery._approximate_name_equivalent(
                "Charizard ex 151", "Charizard ex 150"
            )
        )

    def test_reverse_suffix_requires_listing_and_card_finish_proof(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/elektek-reverse",
            title="PSA 9 Elektek Reverse",
            current_price=50.0,
            source_type="fixed",
            grader="PSA",
            grade="9",
            card_set="Evolutions",
            card_number="#41/108",
            language="French",
            year=2016,
        )
        reverse_card = {"name": "Elektek", "variants": {"reverse": True, "holo": False}}
        holo_card = {"name": "Elektek", "variants": {"reverse": False, "holo": True}}

        self.assertEqual(
            recovery._proven_finish_display_suffix(lot, "Elektek Reverse"),
            ("reverse", "elektek"),
        )
        self.assertTrue(
            recovery._candidate_name_compatible(lot, "Elektek Reverse", reverse_card)
        )
        self.assertFalse(
            recovery._candidate_name_compatible(lot, "Elektek Reverse", holo_card)
        )

    def test_rainbow_and_gold_are_not_stripped_without_supported_schema(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/rainbow",
            title="PSA 9 Darumacho de Galar VMAX Rainbow",
            current_price=50.0,
            source_type="fixed",
            grader="PSA",
            grade="9",
            card_set="Voltage Eclatant",
            card_number="#187/185",
            language="French",
            year=2020,
        )
        self.assertIsNone(
            recovery._proven_finish_display_suffix(lot, "Darumacho de Galar VMAX Rainbow")
        )
        self.assertIsNone(
            recovery._proven_finish_display_suffix(lot, "Origin Dialga VStar Gold")
        )

    def test_filters_shared_denominator_coordinates_by_exact_name_before_ambiguity(self):
        lot = self._lot()
        sets = (
            {"id": "base1", "cardCount": {"official": 102}},
            {"id": "other102", "cardCount": {"official": 102}},
        )
        base_card = {
            "id": "base1-53",
            "localId": "53",
            "name": "Magnéti",
            "set": {"id": "base1", "name": "Set de Base", "cardCount": {"official": 102}},
        }
        other_card = {
            "id": "other102-53",
            "localId": "53",
            "name": "Autre carte",
            "set": {"id": "other102", "name": "Autre set", "cardCount": {"official": 102}},
        }
        exact = canonical.CanonicalCard(
            status="EXACT",
            card_id="base1-53",
            set_id="base1",
            set_name="Set de base",
            local_id="53",
            full_number="53/102",
            name="Magnéti",
            language_code="fr",
            reason="TCGDEX_EXACT_SET_LOCALID",
        )

        def probe(_lot, *, language_code, set_id, expected_count):
            del _lot, language_code, expected_count
            return base_card if set_id == "base1" else other_card

        def canonicalize(_lot, card, **kwargs):
            del _lot, kwargs
            return exact if card["name"] == "Magnéti" else None

        with mock.patch.object(unique, "_set_index", return_value=sets), \
             mock.patch.object(unique, "_probe_exact_set_coordinate", side_effect=probe), \
             mock.patch.object(unique, "_canonicalize_unique_card", side_effect=canonicalize):
            result = recovery._recover_exact_name_from_ambiguous_coordinate(lot)

        self.assertIsNotNone(result)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "base1-53")

    def test_fuzzy_name_recovers_one_unique_exact_coordinate_candidate(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/brocks-ninetales",
            title="PSA 9 Brock Ninetales",
            current_price=50.0,
            source_type="fixed",
            grader="PSA",
            grade="9",
            card_set="Gym Challenge",
            card_number="#3/132",
            language="English",
            year=2000,
        )
        sets = (
            {"id": "gym2", "cardCount": {"official": 132}},
            {"id": "other132", "cardCount": {"official": 132}},
        )
        cards = {
            "gym2": {
                "id": "gym2-3",
                "localId": "3",
                "name": "Brock's Ninetales",
                "set": {"id": "gym2", "name": "Gym Challenge", "cardCount": {"official": 132}},
            },
            "other132": {
                "id": "other132-3",
                "localId": "3",
                "name": "Unrelated Pokemon",
                "set": {"id": "other132", "name": "Other", "cardCount": {"official": 132}},
            },
        }

        with mock.patch.object(unique, "_set_index", return_value=sets), \
             mock.patch.object(
                 unique,
                 "_probe_exact_set_coordinate",
                 side_effect=lambda _lot, **kw: cards[kw["set_id"]],
             ), \
             mock.patch.object(unique, "_canonicalize_unique_card", return_value=None):
            result = recovery._recover_exact_name_from_ambiguous_coordinate(lot)

        self.assertIsNotNone(result)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "gym2-3")
        self.assertEqual(result.language_code, "en")

    def test_reverse_finish_narrows_two_same_name_coordinate_candidates(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/elektek-reverse",
            title="PSA 9 Elektek Reverse",
            current_price=50.0,
            source_type="fixed",
            grader="PSA",
            grade="9",
            card_set="Evolutions",
            card_number="#41/108",
            language="French",
            year=2016,
        )
        sets = (
            {"id": "reverse-set", "cardCount": {"official": 108}},
            {"id": "holo-set", "cardCount": {"official": 108}},
        )
        cards = {
            "reverse-set": {
                "id": "reverse-set-41",
                "localId": "41",
                "name": "Elektek",
                "variants": {"reverse": True, "holo": False},
                "set": {"id": "reverse-set", "name": "Evolutions", "cardCount": {"official": 108}},
            },
            "holo-set": {
                "id": "holo-set-41",
                "localId": "41",
                "name": "Elektek",
                "variants": {"reverse": False, "holo": True},
                "set": {"id": "holo-set", "name": "Other", "cardCount": {"official": 108}},
            },
        }

        def canonicalize(_lot, card, **kwargs):
            del _lot, kwargs
            return canonical.CanonicalCard(
                status="EXACT",
                card_id=card["id"],
                set_id=card["set"]["id"],
                set_name=str(card["set"].get("name") or ""),
                local_id="41",
                full_number="41/108",
                name="Elektek",
                language_code="fr",
            )

        with mock.patch.object(unique, "_set_index", return_value=sets), \
             mock.patch.object(
                 unique,
                 "_probe_exact_set_coordinate",
                 side_effect=lambda _lot, **kw: cards[kw["set_id"]],
             ), \
             mock.patch.object(unique, "_canonicalize_unique_card", side_effect=canonicalize):
            result = recovery._recover_exact_name_from_ambiguous_coordinate(lot)

        self.assertIsNotNone(result)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "reverse-set-41")

    def test_two_fuzzy_compatible_matches_remain_ambiguous(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/brocks-ninetales",
            title="PSA 9 Brock Ninetales",
            current_price=50.0,
            source_type="fixed",
            grader="PSA",
            grade="9",
            card_set="Gym Challenge",
            card_number="#3/132",
            language="English",
            year=2000,
        )
        sets = (
            {"id": "one", "cardCount": {"official": 132}},
            {"id": "two", "cardCount": {"official": 132}},
        )
        cards = {
            "one": {
                "id": "one-3",
                "localId": "3",
                "name": "Brock's Ninetales",
                "set": {"id": "one", "cardCount": {"official": 132}},
            },
            "two": {
                "id": "two-3",
                "localId": "3",
                "name": "Brock Ninetalez",
                "set": {"id": "two", "cardCount": {"official": 132}},
            },
        }

        with mock.patch.object(unique, "_set_index", return_value=sets), \
             mock.patch.object(
                 unique,
                 "_probe_exact_set_coordinate",
                 side_effect=lambda _lot, **kw: cards[kw["set_id"]],
             ), \
             mock.patch.object(unique, "_canonicalize_unique_card", return_value=None):
            result = recovery._recover_exact_name_from_ambiguous_coordinate(lot)

        self.assertIsNone(result)

    def test_two_exact_name_matches_remain_ambiguous(self):
        lot = self._lot()
        sets = (
            {"id": "one", "cardCount": {"official": 102}},
            {"id": "two", "cardCount": {"official": 102}},
        )
        cards = {
            "one": {"id": "one-53", "localId": "53", "name": "Magnéti", "set": {"id": "one"}},
            "two": {"id": "two-53", "localId": "53", "name": "Magnéti", "set": {"id": "two"}},
        }

        def canonicalize(_lot, card, **kwargs):
            del _lot, kwargs
            return canonical.CanonicalCard(
                status="EXACT",
                card_id=card["id"],
                set_id=card["set"]["id"],
                set_name="",
                local_id="53",
                full_number="53/102",
                name="Magnéti",
                language_code="fr",
            )

        with mock.patch.object(unique, "_set_index", return_value=sets), \
             mock.patch.object(unique, "_probe_exact_set_coordinate", side_effect=lambda _lot, **kw: cards[kw["set_id"]]), \
             mock.patch.object(unique, "_canonicalize_unique_card", side_effect=canonicalize):
            result = recovery._recover_exact_name_from_ambiguous_coordinate(lot)

        self.assertIsNone(result)

    def test_wrapper_only_targets_known_denominator_ambiguity(self):
        lot = self._lot()
        original = canonical.CanonicalCard("AMBIGUOUS", reason="different ambiguity")
        saved = recovery._ORIGINAL_RESOLVER
        recovery._ORIGINAL_RESOLVER = lambda _lot: original
        recovery._NEGATIVE_CACHE.clear()
        recovery._RESULT_CACHE.clear()
        try:
            with mock.patch.object(recovery, "_recover_exact_name_from_ambiguous_coordinate") as probe:
                result = recovery._resolve_with_name_filtered_coordinate(lot)
            self.assertIs(result, original)
            probe.assert_not_called()
        finally:
            recovery._ORIGINAL_RESOLVER = saved
            recovery._NEGATIVE_CACHE.clear()
            recovery._RESULT_CACHE.clear()


if __name__ == "__main__":
    unittest.main()
