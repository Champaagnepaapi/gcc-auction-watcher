from __future__ import annotations

import unittest
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_two_of_three_backport as backport


class V4TCGdexTwoOfThreeBackportTests(unittest.TestCase):
    def setUp(self):
        backport._RESULT_CACHE.clear()
        backport._NEGATIVE_CACHE.clear()
        canonical._DIAGNOSTICS = canonical.MultiMarketDiagnostics()

    @staticmethod
    def lot(**overrides):
        values = dict(
            url="https://gradedcardcenter.com/item/test-two-of-three",
            title="Lugia",
            current_price=50.0,
            source_type="fixed",
            card_set="",
            card_number="9/111",
            language="English",
            year=2000,
        )
        values.update(overrides)
        return watcher.Lot(**values)

    @staticmethod
    def detail(
        *,
        card_id="neo1-9",
        name="Lugia",
        local_id="9",
        set_id="neo1",
        set_name="Neo Genesis",
        official=111,
        release="2000-12-16",
    ):
        return {
            "id": card_id,
            "name": name,
            "localId": local_id,
            "set": {
                "id": set_id,
                "name": set_name,
                "cardCount": {"official": official, "total": official},
                "releaseDate": release,
            },
            "variants": {
                "firstEdition": False,
                "holo": True,
                "normal": False,
                "reverse": False,
            },
        }

    def test_exact_name_plus_full_number_recovers_unique_set(self):
        lot = self.lot(card_set="")
        brief = {"id": "neo1-9", "name": "Lugia", "localId": "9"}
        detail = self.detail()

        with patch.object(
            canonical,
            "_json_get",
            return_value=(200, [brief], {}),
        ), patch.object(
            canonical,
            "_fetch_tcgdex_card_detail",
            return_value=(200, detail),
        ):
            result = backport._recover_unique_name_number(
                lot,
                language_code="en",
                listing_name="Lugia",
                reference="9/111",
            )

        self.assertIsNotNone(result)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.set_id, "neo1")
        self.assertEqual(result.set_name, "Neo Genesis")
        self.assertEqual(result.full_number, "9/111")
        self.assertTrue(result.unique_name_number)
        self.assertEqual(result.reason, "TCGDEX_UNIQUE_NAME_FULL_NUMBER")

    def test_name_plus_full_number_remains_ambiguous_with_two_exact_cards(self):
        lot = self.lot(card_set="")
        briefs = [
            {"id": "seta-9", "name": "Lugia", "localId": "9"},
            {"id": "setb-9", "name": "Lugia", "localId": "9"},
        ]
        details = {
            "seta-9": self.detail(card_id="seta-9", set_id="seta", set_name="Set A"),
            "setb-9": self.detail(card_id="setb-9", set_id="setb", set_name="Set B"),
        }

        def fetch_detail(_language, card_id):
            return 200, details[card_id]

        with patch.object(
            canonical,
            "_json_get",
            return_value=(200, briefs, {}),
        ), patch.object(
            canonical,
            "_fetch_tcgdex_card_detail",
            side_effect=fetch_detail,
        ):
            result = backport._recover_unique_name_number(
                lot,
                language_code="en",
                listing_name="Lugia",
                reference="9/111",
            )

        self.assertEqual(result.status, "AMBIGUOUS")

    def test_denominator_conflict_cannot_recover_set(self):
        lot = self.lot(card_set="", card_number="9/111")
        detail = self.detail(official=102, set_id="wrong", set_name="Wrong Set")
        with patch.object(
            canonical,
            "_json_get",
            return_value=(200, [{"id": "wrong-9", "name": "Lugia", "localId": "9"}], {}),
        ), patch.object(
            canonical,
            "_fetch_tcgdex_card_detail",
            return_value=(200, detail),
        ):
            result = backport._recover_unique_name_number(
                lot,
                language_code="en",
                listing_name="Lugia",
                reference="9/111",
            )
        self.assertIsNone(result)

    def test_numerator_only_name_number_never_recovers_set(self):
        lot = self.lot(card_set="", card_number="9")
        with patch.object(canonical, "_json_get") as network:
            result = backport._recover_unique_name_number(
                lot,
                language_code="en",
                listing_name="Lugia",
                reference="9",
            )
        self.assertIsNone(result)
        network.assert_not_called()

    def test_exact_set_plus_unique_name_recovers_printed_number(self):
        lot = self.lot(card_set="Neo Genesis", card_number="")
        set_payload = {
            "id": "neo1",
            "name": "Neo Genesis",
            "cards": [
                {"id": "neo1-9", "name": "Lugia", "localId": "9"},
                {"id": "neo1-22", "name": "Elekid", "localId": "22"},
            ],
        }

        def json_get(url, **kwargs):
            if url.endswith("/sets/neo1"):
                return 200, set_payload, {}
            if url.endswith("/en/sets"):
                return 200, [{"id": "neo1", "name": "Neo Genesis"}], {}
            if url.endswith("/fr/sets"):
                return 200, [], {}
            raise AssertionError(url)

        with patch.object(canonical, "_json_get", side_effect=json_get), patch.object(
            canonical,
            "_fetch_tcgdex_card_detail",
            return_value=(200, self.detail()),
        ):
            result = backport._recover_unique_set_name(
                lot,
                language_code="en",
                listing_set="Neo Genesis",
                listing_name="Lugia",
                reference="",
            )

        self.assertIsNotNone(result)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "neo1-9")
        self.assertEqual(result.full_number, "9/111")
        self.assertEqual(
            result.reason, "TCGDEX_UNIQUE_SET_NAME_RECOVERED_NUMBER"
        )

    def test_exact_set_plus_duplicate_name_is_ambiguous(self):
        lot = self.lot(card_set="Neo Genesis", card_number="")
        set_payload = {
            "cards": [
                {"id": "neo1-9a", "name": "Lugia", "localId": "9"},
                {"id": "neo1-9b", "name": "Lugia", "localId": "10"},
            ]
        }

        def json_get(url, **kwargs):
            if url.endswith("/sets/neo1"):
                return 200, set_payload, {}
            if url.endswith("/en/sets"):
                return 200, [{"id": "neo1", "name": "Neo Genesis"}], {}
            if url.endswith("/fr/sets"):
                return 200, [], {}
            raise AssertionError(url)

        with patch.object(canonical, "_json_get", side_effect=json_get):
            result = backport._recover_unique_set_name(
                lot,
                language_code="en",
                listing_set="Neo Genesis",
                listing_name="Lugia",
                reference="",
            )
        self.assertEqual(result.status, "AMBIGUOUS")

    def test_exact_set_collision_is_ambiguous(self):
        lot = self.lot(card_set="Mystery Set", card_number="")

        def json_get(url, **kwargs):
            if url.endswith("/en/sets"):
                return 200, [
                    {"id": "set-a", "name": "Mystery Set"},
                    {"id": "set-b", "name": "Mystery Set"},
                ], {}
            return 200, [], {}

        with patch.object(canonical, "_json_get", side_effect=json_get):
            result = backport._recover_unique_set_name(
                lot,
                language_code="en",
                listing_set="Mystery Set",
                listing_name="Lugia",
                reference="",
            )
        self.assertEqual(result.status, "AMBIGUOUS")

    def test_provider_incomplete_detail_is_error_not_clean_no_match(self):
        lot = self.lot(card_set="")
        with patch.object(
            canonical,
            "_json_get",
            return_value=(200, [{"id": "neo1-9", "name": "Lugia", "localId": "9"}], {}),
        ), patch.object(
            canonical,
            "_fetch_tcgdex_card_detail",
            return_value=(500, None),
        ):
            result = backport._recover_unique_name_number(
                lot,
                language_code="en",
                listing_name="Lugia",
                reference="9/111",
            )
        self.assertEqual(result.status, "ERROR")

    def test_single_coordinate_never_triggers_recovery(self):
        lot = self.lot(
            title="",
            card_set="Neo Genesis",
            card_number="",
        )
        with patch.object(canonical, "_json_get") as network:
            result = backport._recover_two_of_three(lot)
        self.assertIsNone(result)
        network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
