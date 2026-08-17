from __future__ import annotations

import unittest
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_exact_coordinate_recovery as recovery


class TestV4TCGdexExactCoordinateRecovery(unittest.TestCase):
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
            url="https://gradedcardcenter.com/item/test",
            title=f"PSA 10 {name}",
            current_price=50.0,
            source_type="FIXED",
            grader="PSA",
            grade="10",
            card_set=card_set,
            card_number=number,
            language=language,
            year=year,
        )

    def test_run_1037_clean_no_match_panel_is_covered_by_exact_registry(self) -> None:
        cases = (
            ("Gloom", "Ruler of the Black Flame", "109/108", "Japanese", 2023, "SV3", "109"),
            ("Oranguru", "VMAX Climax", "212/184", "Japanese", 2021, "S8b", "212"),
            ("Houndoom", "Night Wanderer", "066/064", "Japanese", 2024, "SV6a", "066"),
            ("Ethan's Typhlosion", "Heat Wave Arena", "070/063", "Japanese", 2025, "SV9a", "070"),
            ("Articuno", "Battle Partners", "102/100", "Japanese", 2025, "SV9", "102"),
            ("Hoopa Ex", "Legendary Shine Collection", "012/027", "Japanese", 2015, "CP2", "012"),
            ("Charizard Ex", "151", "185/165", "Japanese", 2023, "SV2a", "185"),
            ("Kadabra", "Shiny Treasure ex", "254/190", "Japanese", 2023, "SV4a", "254"),
            ("Queulorior", "Tempête Argentée", "TG10/TG30", "French", 2022, "swsh12tg", "TG10"),
            ("Léviator Obscur Holo", "Célébrations", "8/82", "French", 2021, "cel25cc", "CC005"),
        )
        for name, card_set, number, language, year, set_id, local_id in cases:
            with self.subTest(name=name, number=number):
                record, _ = recovery._record_for_lot(
                    self._lot(
                        name=name,
                        card_set=card_set,
                        number=number,
                        language=language,
                        year=year,
                    )
                )
                self.assertIsNotNone(record)
                assert record is not None
                self.assertEqual(record.tcgdex_set_id, set_id)
                self.assertEqual(record.tcgdex_local_id, local_id)

    def test_registry_does_not_accept_name_set_number_or_year_conflicts(self) -> None:
        base = dict(
            name="Houndoom",
            card_set="Night Wanderer",
            number="066/064",
            language="Japanese",
            year=2024,
        )
        conflicts = (
            {"name": "Umbreon"},
            {"card_set": "Shiny Treasure ex"},
            {"number": "067/064"},
            {"language": "French"},
            {"year": 2023},
        )
        for change in conflicts:
            values = {**base, **change}
            record, _ = recovery._record_for_lot(self._lot(**values))
            self.assertIsNone(record)

    def test_exact_coordinate_response_must_prove_set_local_id_and_count(self) -> None:
        lot = self._lot(
            name="Houndoom",
            card_set="Night Wanderer",
            number="066/064",
            language="Japanese",
            year=2024,
        )
        record, _ = recovery._record_for_lot(lot)
        assert record is not None
        payload = {
            "id": "SV6a-066",
            "localId": "066",
            "name": "ヘルガー",
            "set": {
                "id": "SV6a",
                "name": "ナイトワンダラー",
                "cardCount": {"official": 64},
            },
            "pricing": {},
            "variants": {},
        }
        result = recovery._canonical_from_exact_coordinate(lot, record, payload)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.set_id, "SV6a")
        self.assertEqual(result.local_id, "066")
        self.assertEqual(result.full_number, "066/064")
        self.assertIn("TCGDEX_EXACT_COORDINATE_RECOVERY", result.reason)

        wrong_set = {**payload, "set": {**payload["set"], "id": "SV4a"}}
        self.assertIsNone(recovery._canonical_from_exact_coordinate(lot, record, wrong_set))

        wrong_local = {**payload, "localId": "067"}
        self.assertIsNone(recovery._canonical_from_exact_coordinate(lot, record, wrong_local))

        wrong_count = {**payload, "set": {**payload["set"], "cardCount": {"official": 65}}}
        self.assertIsNone(recovery._canonical_from_exact_coordinate(lot, record, wrong_count))

    def test_transient_recovery_failure_is_not_clean_no_match(self) -> None:
        lot = self._lot(
            name="Houndoom",
            card_set="Night Wanderer",
            number="066/064",
            language="Japanese",
            year=2024,
        )
        record, _ = recovery._record_for_lot(lot)
        assert record is not None
        with patch.object(canonical, "_json_get", return_value=(429, None, "rate limited")):
            result = recovery._fetch_exact_coordinate(lot, record)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "ERROR")

    def test_nontransient_missing_coordinate_stays_clean_no_match(self) -> None:
        lot = self._lot(
            name="Houndoom",
            card_set="Night Wanderer",
            number="066/064",
            language="Japanese",
            year=2024,
        )
        record, _ = recovery._record_for_lot(lot)
        assert record is not None
        with patch.object(canonical, "_json_get", return_value=(404, None, "missing")):
            self.assertIsNone(recovery._fetch_exact_coordinate(lot, record))

    def test_reclassification_keeps_attempt_count_and_replaces_no_match(self) -> None:
        diagnostics = canonical.MultiMarketDiagnostics()
        diagnostics.tcgdex_attempted = 1
        diagnostics.tcgdex_no_match = 1
        with patch.object(canonical, "_DIAGNOSTICS", diagnostics):
            recovery._reclassify_original_no_match(canonical.CanonicalCard("EXACT"))
            self.assertEqual(diagnostics.tcgdex_attempted, 1)
            self.assertEqual(diagnostics.tcgdex_no_match, 0)
            self.assertEqual(diagnostics.tcgdex_exact, 1)


if __name__ == "__main__":
    unittest.main()
