from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as canonical
import v4_raw_consensus as raw_consensus
import v4_tcgdex_detailed_variants as detailed
import v4_tcgdex_rainbow_variant_recovery as rainbow


class V4TCGdexRainbowVariantRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        rainbow._RESULT_CACHE.clear()
        rainbow._NEGATIVE_CACHE.clear()

        self._watcher_special = dict(
            watcher.COMMERCIAL_DIMENSION_PATTERNS.get("special_finish", {})
        )
        self._raw_special = dict(
            raw_consensus.MULTILINGUAL_DIMENSION_PATTERNS.get("special_finish", {})
        )
        self._detailed_foil = dict(detailed._SPECIAL_FINISH_BY_FOIL)
        self._decompose = raw_consensus.decompose_commercial_variant
        self._dimensions_installed = rainbow._DIMENSIONS_INSTALLED
        self._original_decompose = rainbow._ORIGINAL_DECOMPOSE_VARIANT

    def tearDown(self) -> None:
        watcher.COMMERCIAL_DIMENSION_PATTERNS.setdefault("special_finish", {}).clear()
        watcher.COMMERCIAL_DIMENSION_PATTERNS["special_finish"].update(
            self._watcher_special
        )
        raw_consensus.MULTILINGUAL_DIMENSION_PATTERNS.setdefault(
            "special_finish", {}
        ).clear()
        raw_consensus.MULTILINGUAL_DIMENSION_PATTERNS["special_finish"].update(
            self._raw_special
        )
        detailed._SPECIAL_FINISH_BY_FOIL.clear()
        detailed._SPECIAL_FINISH_BY_FOIL.update(self._detailed_foil)
        raw_consensus.decompose_commercial_variant = self._decompose
        rainbow._DIMENSIONS_INSTALLED = self._dimensions_installed
        rainbow._ORIGINAL_DECOMPOSE_VARIANT = self._original_decompose

    def _lot(
        self,
        *,
        name: str = "Fille en Kimono Rainbow",
        number: str = "205/195",
        card_set: str = "Tempête Argentée",
    ) -> watcher.Lot:
        return watcher.Lot(
            url="https://gradedcardcenter.com/item/test-rainbow",
            title=f"PSA 9 {name}",
            current_price=80.0,
            source_type="fixed",
            grader="PSA",
            grade="9",
            card_set=card_set,
            card_number=number,
            language="French",
            year=2022,
            listing_text=(
                f"{name} #{number} {card_set} French PSA 9"
            ),
        )

    def _card(
        self,
        *,
        name: str = "Fille en Kimono",
        local_id: str = "205",
        set_id: str = "swsh12",
        official_count: int = 195,
        detailed_variants=None,
    ) -> dict:
        if detailed_variants is None:
            detailed_variants = [
                {
                    "type": "holo",
                    "size": "standard",
                    "foil": "rainbow",
                    "languages": ["fr"],
                }
            ]
        return {
            "id": f"{set_id}-{local_id}",
            "localId": local_id,
            "name": name,
            "set": {
                "id": set_id,
                "name": "Tempête Argentée",
                "cardCount": {"official": official_count, "total": 215},
            },
            "pricing": {},
            "variants": {
                "normal": False,
                "holo": True,
                "reverse": False,
                "firstEdition": False,
            },
            "variants_detailed": detailed_variants,
        }

    def _recover(self, lot: watcher.Lot, card: dict):
        with patch.object(
            canonical,
            "_json_get",
            side_effect=[
                (
                    200,
                    [{"id": "swsh12", "name": "Tempête Argentée"}],
                    {},
                ),
                (200, card, {}),
            ],
        ):
            return rainbow._recover_rainbow_from_exact_set_name(lot)

    def test_only_trailing_rainbow_is_a_display_suffix(self) -> None:
        self.assertEqual(
            rainbow._rainbow_base_name("Fille en Kimono Rainbow"),
            canonical._normalize("Fille en Kimono"),
        )
        self.assertEqual(rainbow._rainbow_base_name("Rainbow Fille en Kimono"), "")
        self.assertEqual(rainbow._rainbow_base_name("Rainbow"), "")
        self.assertEqual(rainbow._rainbow_base_name("Fille en Kimono"), "")

    def test_rainbow_requires_holo_plus_explicit_rainbow_foil(self) -> None:
        good, state, _ = rainbow._rainbow_detail_proven(
            self._card(), language_code="fr"
        )
        self.assertTrue(good)
        self.assertEqual(state, "USABLE")

        for variants in (
            [{"type": "holo", "foil": "cosmos", "languages": ["fr"]}],
            [{"type": "normal", "foil": "rainbow", "languages": ["fr"]}],
            [{"type": "reverse", "foil": "rainbow", "languages": ["fr"]}],
        ):
            with self.subTest(variants=variants):
                proven, _, _ = rainbow._rainbow_detail_proven(
                    self._card(detailed_variants=variants), language_code="fr"
                )
                self.assertFalse(proven)

    def test_missing_malformed_or_wrong_language_detail_fails_closed(self) -> None:
        cases = (
            self._card(detailed_variants=[]),
            {**self._card(), "variants_detailed": "rainbow"},
            self._card(
                detailed_variants=[
                    {"type": "holo", "foil": "rainbow", "languages": ["en"]}
                ]
            ),
        )
        for card in cases:
            with self.subTest(card=card):
                proven, state, _ = rainbow._rainbow_detail_proven(
                    card, language_code="fr"
                )
                self.assertFalse(proven)
                self.assertNotEqual(state, "USABLE")

    def test_exact_coordinate_and_rainbow_proof_recovers_card(self) -> None:
        result = self._recover(self._lot(), self._card())
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "swsh12-205")
        self.assertEqual(result.local_id, "205")
        self.assertEqual(result.full_number, "205/195")
        self.assertEqual(result.name, "Fille en Kimono")
        self.assertEqual(result.language_code, "fr")
        self.assertEqual(
            result.variants[detailed.DETAILED_STATE_KEY],
            "USABLE",
        )

    def test_wrong_name_number_denominator_or_set_count_cannot_recover(self) -> None:
        cases = (
            (self._lot(), self._card(name="Fille en Kimono V")),
            (self._lot(number="204/195"), self._card()),
            (self._lot(number="205/194"), self._card()),
            (self._lot(), self._card(official_count=194)),
        )
        for lot, card in cases:
            with self.subTest(lot=lot.card_number, card=card.get("name")):
                self.assertIsNone(self._recover(lot, card))

    def test_multiple_or_missing_exact_sets_do_not_guess(self) -> None:
        lot = self._lot()
        with patch.object(
            canonical,
            "_json_get",
            return_value=(
                200,
                [
                    {"id": "swsh12", "name": "Tempête Argentée"},
                    {"id": "other", "name": "Tempête Argentée"},
                ],
                {},
            ),
        ):
            self.assertIsNone(rainbow._recover_rainbow_from_exact_set_name(lot))
        with patch.object(canonical, "_json_get", return_value=(200, [], {})):
            self.assertIsNone(rainbow._recover_rainbow_from_exact_set_name(lot))

    def test_commercial_parsers_treat_rainbow_as_explicit_special_finish(self) -> None:
        rainbow._install_rainbow_dimension_support()

        listing = watcher.expected_commercial_dimensions(self._lot())
        self.assertEqual(listing.get("special_finish"), "rainbow")

        multilingual = raw_consensus.parse_multilingual_commercial_dimensions(
            "Fille en Kimono Rainbow"
        )
        self.assertEqual(multilingual.get("special_finish"), "rainbow")

        decomposed = raw_consensus.decompose_commercial_variant(
            "Holofoil Rainbow"
        )
        self.assertEqual(decomposed.get("finish"), "holo")
        self.assertEqual(decomposed.get("special_finish"), "rainbow")

    def test_conflicting_special_finishes_remain_conflict(self) -> None:
        rainbow._install_rainbow_dimension_support()
        parsed = raw_consensus.parse_multilingual_commercial_dimensions(
            "Rainbow Master Ball"
        )
        self.assertEqual(parsed.get("special_finish"), "__conflict__")
        decomposed = raw_consensus.decompose_commercial_variant(
            "Rainbow Master Ball"
        )
        self.assertEqual(decomposed.get("special_finish"), "__conflict__")

    def test_detailed_gate_requires_same_rainbow_microvariant(self) -> None:
        rainbow._install_rainbow_dimension_support()
        result = self._recover(self._lot(), self._card())
        self.assertIsNotNone(result)
        assert result is not None

        exact = detailed.detailed_variant_decision(
            result,
            {"special_finish": "rainbow"},
        )
        self.assertTrue(exact.compatible)
        self.assertEqual(exact.status, "EXACT")
        self.assertEqual(
            exact.selected.dimension_map().get("special_finish"),
            "rainbow",
        )

        conflict = detailed.detailed_variant_decision(
            result,
            {"special_finish": "master_ball"},
        )
        self.assertFalse(conflict.compatible)
        self.assertEqual(conflict.status, "CONFLICT")

    def test_poketrace_candidate_without_rainbow_is_rejected(self) -> None:
        rainbow._install_rainbow_dimension_support()
        lot = self._lot()
        rainbow_candidate = {
            "variant": "Holofoil Rainbow",
            "rarity": "Rare",
            "name": "Fille en Kimono",
        }
        ordinary_holo = {
            "variant": "Holofoil",
            "rarity": "Rare",
            "name": "Fille en Kimono",
        }
        self.assertTrue(
            canonical._candidate_commercially_compatible(lot, rainbow_candidate)
        )
        self.assertFalse(
            canonical._candidate_commercially_compatible(lot, ordinary_holo)
        )

    def test_no_match_is_reclassified_to_exact_without_new_attempt(self) -> None:
        lot = self._lot()
        diagnostics = canonical.MultiMarketDiagnostics()

        def original(_lot: watcher.Lot) -> canonical.CanonicalCard:
            diagnostics.tcgdex_attempted += 1
            diagnostics.tcgdex_no_match += 1
            return canonical.CanonicalCard("NO_MATCH")

        recovered = canonical.CanonicalCard(
            "EXACT",
            card_id="swsh12-205",
            set_id="swsh12",
            local_id="205",
            full_number="205/195",
            name="Fille en Kimono",
            language_code="fr",
            reason="TCGDEX_EXACT_SET_LOCALID",
        )
        previous = rainbow._ORIGINAL_RESOLVER
        rainbow._ORIGINAL_RESOLVER = original
        try:
            with patch.object(canonical, "_DIAGNOSTICS", diagnostics), patch.object(
                rainbow,
                "_recover_rainbow_from_exact_set_name",
                return_value=recovered,
            ):
                result = rainbow._resolve_with_rainbow_variant_recovery(lot)
        finally:
            rainbow._ORIGINAL_RESOLVER = previous

        self.assertEqual(result.status, "EXACT")
        self.assertEqual(diagnostics.tcgdex_attempted, 1)
        self.assertEqual(diagnostics.tcgdex_no_match, 0)
        self.assertEqual(diagnostics.tcgdex_exact, 1)

    def test_transient_recovery_error_remains_fail_closed(self) -> None:
        lot = self._lot()
        diagnostics = canonical.MultiMarketDiagnostics()

        def original(_lot: watcher.Lot) -> canonical.CanonicalCard:
            diagnostics.tcgdex_attempted += 1
            diagnostics.tcgdex_no_match += 1
            return canonical.CanonicalCard("NO_MATCH")

        previous = rainbow._ORIGINAL_RESOLVER
        rainbow._ORIGINAL_RESOLVER = original
        try:
            with patch.object(canonical, "_DIAGNOSTICS", diagnostics), patch.object(
                rainbow,
                "_recover_rainbow_from_exact_set_name",
                return_value=canonical.CanonicalCard(
                    "ERROR", reason="TCGdex rainbow transient HTTP 503"
                ),
            ):
                result = rainbow._resolve_with_rainbow_variant_recovery(lot)
        finally:
            rainbow._ORIGINAL_RESOLVER = previous

        self.assertEqual(result.status, "ERROR")
        self.assertEqual(diagnostics.tcgdex_no_match, 0)
        self.assertEqual(diagnostics.tcgdex_error, 1)

    def test_runtime_installs_rainbow_after_detailed_variant_gate(self) -> None:
        source = Path("run_watcher_multimarket.py").read_text(encoding="utf-8")
        detailed_marker = "install_v4_tcgdex_detailed_variants()"
        rainbow_marker = "install_v4_tcgdex_rainbow_variant_recovery()"
        self.assertIn(rainbow_marker, source)
        self.assertGreater(source.index(rainbow_marker), source.index(detailed_marker))


if __name__ == "__main__":
    unittest.main()
