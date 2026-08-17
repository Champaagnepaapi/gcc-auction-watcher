from __future__ import annotations

import unittest
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_generalized_coordinate_recovery as recovery


class TestV4TCGdexGeneralizedCoordinateRecovery(unittest.TestCase):
    def setUp(self) -> None:
        recovery._RECOVERY_CACHE.clear()
        recovery._RECOVERY_NEGATIVE_CACHE.clear()

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

    def test_run_1043_set_aliases_are_set_level_not_per_card(self) -> None:
        cases = (
            ("Japanese", "Eevee Heroes", "030/069", "S6a", 69, ""),
            ("Japanese", "Brilliant Stars", "015/100", "S9", 100, ""),
            ("French", "Promo Mega Evolution", "023/MEP", "mep", 0, "MEP"),
            ("French", "Promos Écarlate et Violet", "209", "svp", 225, ""),
        )
        for language, card_set, number, set_id, count, suffix in cases:
            with self.subTest(card_set=card_set):
                lot = self._lot(
                    name="Any reviewed card name",
                    card_set=card_set,
                    number=number,
                    language=language,
                    year=2025,
                )
                language_code, listing_set, reference, _, _, _ = recovery._lot_components(lot)
                alias = recovery._SET_ALIASES_BY_KEY.get(
                    recovery._alias_key(language_code, listing_set)
                )
                self.assertIsNotNone(alias)
                assert alias is not None
                self.assertEqual(alias.tcgdex_set_id, set_id)
                self.assertEqual(alias.tcgdex_official_count, count)
                self.assertEqual(alias.required_reference_suffix, suffix)
                self.assertTrue(recovery._validate_reference_for_alias(reference, alias))

    def test_japanese_alias_requires_exact_numeric_denominator(self) -> None:
        lot = self._lot(
            name="Jolteon V",
            card_set="Eevee Heroes",
            number="030/069",
            language="Japanese",
            year=2021,
        )
        alias = recovery._SET_ALIASES_BY_KEY[("ja", recovery._norm_text("Eevee Heroes"))]
        self.assertTrue(recovery._validate_reference_for_alias(lot.card_number, alias))
        self.assertFalse(recovery._validate_reference_for_alias("030/070", alias))
        self.assertFalse(recovery._validate_reference_for_alias("030", alias))

    def test_mep_alias_requires_exact_namespace_suffix(self) -> None:
        alias = recovery._SET_ALIASES_BY_KEY[("fr", recovery._norm_text("Promo Mega Evolution"))]
        self.assertTrue(recovery._validate_reference_for_alias("023/MEP", alias))
        self.assertFalse(recovery._validate_reference_for_alias("023/SVP", alias))
        self.assertFalse(recovery._validate_reference_for_alias("023", alias))

    def test_jolteon_japanese_coordinate_can_be_proven_without_localized_name(self) -> None:
        lot = self._lot(
            name="Jolteon V",
            card_set="Eevee Heroes",
            number="030/069",
            language="Japanese",
            year=2021,
        )
        result = recovery._canonical_from_coordinate(
            lot,
            self._card(
                card_id="S6a-030",
                local_id="030",
                name="",
                set_id="S6a",
                count=69,
            ),
            language_code="ja",
            listing_set="Eevee Heroes",
            listing_name="Jolteon V",
            expected_set_id="S6a",
            expected_count=69,
            allow_localized_name_mismatch=True,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "S6a-030")
        self.assertEqual(result.name, "Jolteon V")
        self.assertEqual(result.reason, "TCGDEX_EXACT_SET_LOCALID")
        self.assertFalse(result.unique_name_number)

    def test_japanese_coordinate_rejects_wrong_set_localid_or_count(self) -> None:
        lot = self._lot(
            name="Charizard VStar",
            card_set="Brilliant Stars",
            number="015/100",
            language="Japanese",
            year=2022,
        )
        base = self._card(
            card_id="S9-015",
            local_id="015",
            name="リザードンVSTAR",
            set_id="S9",
            count=100,
        )
        kwargs = dict(
            language_code="ja",
            listing_set="Brilliant Stars",
            listing_name="Charizard VStar",
            expected_set_id="S9",
            expected_count=100,
            allow_localized_name_mismatch=True,
        )
        self.assertIsNotNone(recovery._canonical_from_coordinate(lot, base, **kwargs))
        wrong_set = {**base, "set": {**base["set"], "id": "S8"}}
        self.assertIsNone(recovery._canonical_from_coordinate(lot, wrong_set, **kwargs))
        wrong_local = {**base, "localId": "016"}
        self.assertIsNone(recovery._canonical_from_coordinate(lot, wrong_local, **kwargs))
        wrong_count = {**base, "set": {**base["set"], "cardCount": {"official": 99}}}
        self.assertIsNone(recovery._canonical_from_coordinate(lot, wrong_count, **kwargs))

    def test_promo_alias_still_requires_same_language_card_name(self) -> None:
        lot = self._lot(
            name="Fulguris",
            card_set="Promos Écarlate et Violet",
            number="209",
            language="French",
            year=2025,
        )
        good = self._card(
            card_id="svp-209",
            local_id="209",
            name="Fulguris",
            set_id="svp",
            count=225,
        )
        result = recovery._canonical_from_coordinate(
            lot,
            good,
            language_code="fr",
            listing_set="Promos Écarlate et Violet",
            listing_name="Fulguris",
            expected_set_id="svp",
            expected_count=225,
            allow_localized_name_mismatch=False,
        )
        self.assertIsNotNone(result)
        wrong_name = {**good, "name": "Pikachu"}
        self.assertIsNone(
            recovery._canonical_from_coordinate(
                lot,
                wrong_name,
                language_code="fr",
                listing_set="Promos Écarlate et Violet",
                listing_name="Fulguris",
                expected_set_id="svp",
                expected_count=225,
                allow_localized_name_mismatch=False,
            )
        )

    def test_mega_charizard_hyphenation_is_normalized_but_name_conflict_is_not(self) -> None:
        lot = self._lot(
            name="Méga-Dracaufeu X Ex",
            card_set="Promo Mega Evolution",
            number="023/MEP",
            language="French",
            year=2025,
        )
        good = self._card(
            card_id="mep-023",
            local_id="023",
            name="Méga-Dracaufeu X-ex",
            set_id="mep",
            count=0,
        )
        result = recovery._canonical_from_coordinate(
            lot,
            good,
            language_code="fr",
            listing_set="Promo Mega Evolution",
            listing_name="Méga-Dracaufeu X Ex",
            expected_set_id="mep",
            expected_count=0,
            allow_localized_name_mismatch=False,
        )
        self.assertIsNotNone(result)
        bad = {**good, "name": "Méga-Lucario ex"}
        self.assertIsNone(
            recovery._canonical_from_coordinate(
                lot,
                bad,
                language_code="fr",
                listing_set="Promo Mega Evolution",
                listing_name="Méga-Dracaufeu X Ex",
                expected_set_id="mep",
                expected_count=0,
                allow_localized_name_mismatch=False,
            )
        )

    def test_holo_and_gold_are_bounded_trailing_display_suffixes(self) -> None:
        self.assertIn("pikachu", recovery._name_candidates("Pikachu Holo"))
        self.assertIn("memoire ball", recovery._name_candidates("Mémoire Ball Gold"))
        self.assertEqual(recovery._name_candidates("Holo Pikachu"), {"holo pikachu"})
        self.assertEqual(recovery._name_candidates("Golden Pikachu"), {"golden pikachu"})

    def test_pikachu_holo_exact_set_coordinate_matches_base_name(self) -> None:
        lot = self._lot(
            name="Pikachu Holo",
            card_set="Forces Temporelles",
            number="051/162",
            language="French",
            year=2026,
        )
        card = self._card(
            card_id="sv05-051",
            local_id="051",
            name="Pikachu",
            set_id="sv05",
            count=162,
        )
        result = recovery._canonical_from_coordinate(
            lot,
            card,
            language_code="fr",
            listing_set="Forces Temporelles",
            listing_name="Pikachu Holo",
            expected_set_id="sv05",
            expected_count=None,
            allow_localized_name_mismatch=False,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.name, "Pikachu")

    def test_memory_ball_gold_exact_set_coordinate_matches_base_name(self) -> None:
        lot = self._lot(
            name="Mémoire Ball Gold",
            card_set="Harmonie des Esprits",
            number="250/236",
            language="French",
            year=2019,
        )
        card = self._card(
            card_id="sm11-250",
            local_id="250",
            name="Mémoire Ball",
            set_id="sm11",
            count=236,
        )
        result = recovery._canonical_from_coordinate(
            lot,
            card,
            language_code="fr",
            listing_set="Harmonie des Esprits",
            listing_name="Mémoire Ball Gold",
            expected_set_id="sm11",
            expected_count=None,
            allow_localized_name_mismatch=False,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.card_id, "sm11-250")
        self.assertEqual(result.name, "Mémoire Ball")

    def test_dynamic_exact_set_recovery_requires_one_exact_set(self) -> None:
        lot = self._lot(
            name="Pikachu Holo",
            card_set="Forces Temporelles",
            number="051/162",
            language="French",
            year=2026,
        )
        card = self._card(
            card_id="sv05-051",
            local_id="051",
            name="Pikachu",
            set_id="sv05",
            count=162,
        )
        with patch.object(
            canonical,
            "_json_get",
            side_effect=[
                (200, [{"id": "sv05", "name": "Forces Temporelles"}], {}),
                (200, card, {}),
            ],
        ):
            result = recovery._recover_from_exact_set_name(lot)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "EXACT")

        with patch.object(
            canonical,
            "_json_get",
            return_value=(
                200,
                [{"id": "sv05"}, {"id": "other"}],
                {},
            ),
        ):
            self.assertIsNone(recovery._recover_from_exact_set_name(lot))

    def test_no_display_suffix_does_not_repeat_normal_exact_set_lookup(self) -> None:
        lot = self._lot(
            name="Pikachu",
            card_set="Forces Temporelles",
            number="051/162",
            language="French",
            year=2026,
        )
        with patch.object(canonical, "_json_get") as request:
            self.assertIsNone(recovery._recover_from_exact_set_name(lot))
        request.assert_not_called()

    def test_transient_recovery_reclassifies_original_no_match_as_error(self) -> None:
        lot = self._lot(
            name="Fulguris",
            card_set="Promos Écarlate et Violet",
            number="209",
            language="French",
            year=2025,
        )
        diagnostics = canonical.MultiMarketDiagnostics()

        def original(_lot: watcher.Lot) -> canonical.CanonicalCard:
            diagnostics.tcgdex_attempted += 1
            diagnostics.tcgdex_no_match += 1
            return canonical.CanonicalCard("NO_MATCH")

        previous = recovery._ORIGINAL_RESOLVER
        recovery._ORIGINAL_RESOLVER = original
        try:
            with patch.object(canonical, "_DIAGNOSTICS", diagnostics), patch.object(
                recovery,
                "_recover_from_set_alias",
                return_value=canonical.CanonicalCard("ERROR", reason="transient"),
            ):
                result = recovery._resolve_with_generalized_coordinate_recovery(lot)
        finally:
            recovery._ORIGINAL_RESOLVER = previous
        self.assertEqual(result.status, "ERROR")
        self.assertEqual(diagnostics.tcgdex_attempted, 1)
        self.assertEqual(diagnostics.tcgdex_no_match, 0)
        self.assertEqual(diagnostics.tcgdex_error, 1)

    def test_exact_recovery_replaces_no_match_without_changing_attempt_count(self) -> None:
        lot = self._lot(
            name="Fulguris",
            card_set="Promos Écarlate et Violet",
            number="209",
            language="French",
            year=2025,
        )
        diagnostics = canonical.MultiMarketDiagnostics()

        def original(_lot: watcher.Lot) -> canonical.CanonicalCard:
            diagnostics.tcgdex_attempted += 1
            diagnostics.tcgdex_no_match += 1
            return canonical.CanonicalCard("NO_MATCH")

        recovered = canonical.CanonicalCard(
            "EXACT",
            card_id="svp-209",
            set_id="svp",
            local_id="209",
            reason="TCGDEX_EXACT_SET_LOCALID",
        )
        previous = recovery._ORIGINAL_RESOLVER
        recovery._ORIGINAL_RESOLVER = original
        try:
            with patch.object(canonical, "_DIAGNOSTICS", diagnostics), patch.object(
                recovery, "_recover_from_set_alias", return_value=recovered
            ):
                result = recovery._resolve_with_generalized_coordinate_recovery(lot)
        finally:
            recovery._ORIGINAL_RESOLVER = previous
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(diagnostics.tcgdex_attempted, 1)
        self.assertEqual(diagnostics.tcgdex_no_match, 0)
        self.assertEqual(diagnostics.tcgdex_exact, 1)


if __name__ == "__main__":
    unittest.main()
