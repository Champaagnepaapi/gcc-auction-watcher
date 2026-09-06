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
