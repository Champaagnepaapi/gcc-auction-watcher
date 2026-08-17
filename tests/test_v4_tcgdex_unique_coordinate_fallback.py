from __future__ import annotations

import unittest
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_unique_coordinate_fallback as fallback


class TestV4TCGdexUniqueCoordinateFallback(unittest.TestCase):
    def setUp(self) -> None:
        fallback._SET_INDEX_CACHE.clear()
        fallback._RESULT_CACHE.clear()
        fallback._NEGATIVE_CACHE.clear()

    def _lot(
        self,
        *,
        name: str,
        card_set: str,
        number: str,
        language: str,
        year: int = 2025,
    ) -> watcher.Lot:
        return watcher.Lot(
            url="https://gradedcardcenter.com/item/unique-coordinate-test",
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

    def _set(self, set_id: str, count: int) -> dict:
        return {
            "id": set_id,
            "name": f"Set {set_id}",
            "cardCount": {"official": count, "total": count},
        }

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
                "name": f"Set {set_id}",
                "cardCount": {"official": count, "total": count},
            },
            "pricing": {},
            "variants": {},
        }

    def test_unique_numeric_denominator_recovers_japanese_localized_name(self) -> None:
        lot = self._lot(
            name="Dedenne",
            card_set="VMAX Climax",
            number="200/184",
            language="Japanese",
            year=2021,
        )
        card = self._card(
            card_id="S8b-200",
            local_id="200",
            name="デデンネ",
            set_id="S8b",
            count=184,
        )
        with patch.object(
            canonical,
            "_json_get",
            side_effect=[
                (200, [self._set("S8b", 184), self._set("S9", 100)], {}),
                (200, card, {}),
            ],
        ):
            result = fallback._recover_unique_coordinate(lot)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "S8b-200")
        self.assertEqual(result.set_id, "S8b")
        self.assertEqual(result.name, "Dedenne")
        self.assertEqual(result.reason, "TCGDEX_EXACT_SET_LOCALID")

    def test_two_cards_with_same_numeric_coordinate_remain_ambiguous(self) -> None:
        lot = self._lot(
            name="Dedenne",
            card_set="VMAX Climax",
            number="200/184",
            language="Japanese",
        )
        first = self._card(
            card_id="A-200", local_id="200", name="デデンネ", set_id="A", count=184
        )
        second = self._card(
            card_id="B-200", local_id="200", name="別のカード", set_id="B", count=184
        )
        with patch.object(
            canonical,
            "_json_get",
            side_effect=[
                (200, [self._set("A", 184), self._set("B", 184)], {}),
                (200, first, {}),
                (200, second, {}),
            ],
        ):
            result = fallback._recover_unique_coordinate(lot)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "AMBIGUOUS")

    def test_wrong_numeric_denominator_has_no_coordinate_candidate(self) -> None:
        lot = self._lot(
            name="Dedenne",
            card_set="VMAX Climax",
            number="200/185",
            language="Japanese",
        )
        with patch.object(
            canonical,
            "_json_get",
            return_value=(200, [self._set("S8b", 184)], {}),
        ) as request:
            result = fallback._recover_unique_coordinate(lot)
        self.assertIsNone(result)
        request.assert_called_once()

    def test_missing_card_count_in_set_index_fails_closed(self) -> None:
        lot = self._lot(
            name="Dedenne",
            card_set="VMAX Climax",
            number="200/184",
            language="Japanese",
        )
        with patch.object(
            canonical,
            "_json_get",
            return_value=(200, [{"id": "unknown", "name": "Unknown"}], {}),
        ):
            result = fallback._recover_unique_coordinate(lot)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "ERROR")

    def test_exact_namespace_set_id_recovers_without_alias(self) -> None:
        lot = self._lot(
            name="Iono's Wattrel",
            card_set="Scarlet & Violet Promos",
            number="232/SV-P",
            language="Japanese",
        )
        card = self._card(
            card_id="SV-P-232",
            local_id="232",
            name="ナンジャモのカイデン",
            set_id="SV-P",
            count=0,
        )
        with patch.object(
            canonical,
            "_json_get",
            side_effect=[
                (200, [self._set("SV-P", 0), self._set("M-P", 0)], {}),
                (200, card, {}),
            ],
        ):
            result = fallback._recover_unique_coordinate(lot)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.set_id, "SV-P")

    def test_namespace_not_equal_to_any_set_id_stays_no_match(self) -> None:
        lot = self._lot(
            name="Iono's Wattrel",
            card_set="Scarlet & Violet Promos",
            number="232/NOT-A-SET",
            language="Japanese",
        )
        with patch.object(
            canonical,
            "_json_get",
            return_value=(200, [self._set("SV-P", 0)], {}),
        ) as request:
            result = fallback._recover_unique_coordinate(lot)
        self.assertIsNone(result)
        request.assert_called_once()

    def test_unique_alphanumeric_localid_recovers_same_language_name(self) -> None:
        lot = self._lot(
            name="Clamiral de Hisui",
            card_set="SWSH Promo",
            number="SWSH207",
            language="French",
            year=2022,
        )
        detail = self._card(
            card_id="swshp-SWSH207",
            local_id="SWSH207",
            name="Clamiral de Hisui",
            set_id="swshp",
            count=307,
        )
        with patch.object(
            canonical,
            "_json_get",
            return_value=(
                200,
                [{"id": "swshp-SWSH207", "localId": "SWSH207"}],
                {},
            ),
        ), patch.object(
            canonical,
            "_fetch_tcgdex_card_detail",
            return_value=(200, detail),
        ):
            result = fallback._recover_unique_coordinate(lot)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "swshp-SWSH207")

    def test_non_unique_alphanumeric_localid_is_ambiguous_before_detail(self) -> None:
        lot = self._lot(
            name="Clamiral de Hisui",
            card_set="SWSH Promo",
            number="SWSH207",
            language="French",
        )
        with patch.object(
            canonical,
            "_json_get",
            return_value=(
                200,
                [
                    {"id": "one", "localId": "SWSH207"},
                    {"id": "two", "localId": "SWSH207"},
                ],
                {},
            ),
        ), patch.object(canonical, "_fetch_tcgdex_card_detail") as detail:
            result = fallback._recover_unique_coordinate(lot)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "AMBIGUOUS")
        detail.assert_not_called()

    def test_same_script_card_name_conflict_blocks_unique_coordinate(self) -> None:
        lot = self._lot(
            name="Clamiral de Hisui",
            card_set="SWSH Promo",
            number="SWSH207",
            language="French",
        )
        detail = self._card(
            card_id="swshp-SWSH207",
            local_id="SWSH207",
            name="Pikachu",
            set_id="swshp",
            count=307,
        )
        with patch.object(
            canonical,
            "_json_get",
            return_value=(
                200,
                [{"id": "swshp-SWSH207", "localId": "SWSH207"}],
                {},
            ),
        ), patch.object(
            canonical,
            "_fetch_tcgdex_card_detail",
            return_value=(200, detail),
        ):
            result = fallback._recover_unique_coordinate(lot)
        self.assertIsNone(result)

    def test_same_script_japanese_conflict_is_not_hidden_by_script_bridge(self) -> None:
        lot = self._lot(
            name="ピカチュウ",
            card_set="Japanese Set",
            number="200/184",
            language="Japanese",
        )
        card = self._card(
            card_id="S8b-200",
            local_id="200",
            name="デデンネ",
            set_id="S8b",
            count=184,
        )
        with patch.object(
            canonical,
            "_json_get",
            side_effect=[
                (200, [self._set("S8b", 184)], {}),
                (200, card, {}),
            ],
        ):
            result = fallback._recover_unique_coordinate(lot)
        self.assertIsNone(result)

    def test_numeric_localid_without_denominator_does_not_make_network_call(self) -> None:
        lot = self._lot(
            name="Pikachu",
            card_set="Unknown",
            number="025",
            language="English",
        )
        with patch.object(canonical, "_json_get") as request:
            result = fallback._recover_unique_coordinate(lot)
        self.assertIsNone(result)
        request.assert_not_called()

    def test_set_index_http_failure_is_error_not_clean_no_match(self) -> None:
        lot = self._lot(
            name="Dedenne",
            card_set="VMAX Climax",
            number="200/184",
            language="Japanese",
        )
        with patch.object(canonical, "_json_get", return_value=(500, {}, {})):
            result = fallback._recover_unique_coordinate(lot)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "ERROR")

    def test_coordinate_probe_http_failure_is_error_not_clean_no_match(self) -> None:
        lot = self._lot(
            name="Dedenne",
            card_set="VMAX Climax",
            number="200/184",
            language="Japanese",
        )
        with patch.object(
            canonical,
            "_json_get",
            side_effect=[
                (200, [self._set("S8b", 184)], {}),
                (500, {}, {}),
            ],
        ):
            result = fallback._recover_unique_coordinate(lot)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "ERROR")

    def test_set_index_is_cached_per_language(self) -> None:
        with patch.object(
            canonical,
            "_json_get",
            return_value=(200, [self._set("S8b", 184)], {}),
        ) as request:
            first = fallback._set_index("ja")
            second = fallback._set_index("ja")
        self.assertEqual(first, second)
        request.assert_called_once()

    def _assert_reclassification(self, status: str, counter: str) -> None:
        lot = self._lot(
            name="Dedenne",
            card_set="VMAX Climax",
            number="200/184",
            language="Japanese",
        )
        diagnostics = canonical.MultiMarketDiagnostics()

        def original(_lot: watcher.Lot) -> canonical.CanonicalCard:
            diagnostics.tcgdex_attempted += 1
            diagnostics.tcgdex_no_match += 1
            return canonical.CanonicalCard("NO_MATCH")

        previous = fallback._ORIGINAL_RESOLVER
        fallback._ORIGINAL_RESOLVER = original
        try:
            with patch.object(canonical, "_DIAGNOSTICS", diagnostics), patch.object(
                fallback,
                "_recover_unique_coordinate",
                return_value=canonical.CanonicalCard(status, reason="test"),
            ):
                result = fallback._resolve_with_unique_coordinate_fallback(lot)
        finally:
            fallback._ORIGINAL_RESOLVER = previous
        self.assertEqual(result.status, status)
        self.assertEqual(diagnostics.tcgdex_attempted, 1)
        self.assertEqual(diagnostics.tcgdex_no_match, 0)
        self.assertEqual(getattr(diagnostics, counter), 1)

    def test_exact_reclassifies_original_no_match(self) -> None:
        self._assert_reclassification("EXACT", "tcgdex_exact")

    def test_ambiguous_reclassifies_original_no_match(self) -> None:
        self._assert_reclassification("AMBIGUOUS", "tcgdex_ambiguous")

    def test_error_reclassifies_original_no_match(self) -> None:
        self._assert_reclassification("ERROR", "tcgdex_error")


if __name__ == "__main__":
    unittest.main()
