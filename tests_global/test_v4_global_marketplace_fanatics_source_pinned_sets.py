from __future__ import annotations

import unittest
from unittest.mock import patch

import v4_canonical_multimarket as canonical
import v4_global_fanatics_native_identity as v1
import v4_global_marketplace_fanatics_native_v3 as fanatics
import v4_global_marketplace_fanatics_source_pinned_sets as source_sets
import v4_tcgdex_generalized_coordinate_recovery as generalized
import v4_tcgdex_japanese_set_aliases as shared_aliases
import v4_tcgdex_source_pinned_finish as source_finish


class FanaticsSourcePinnedJapaneseSetTests(unittest.TestCase):
    def _alias(self, listing_set: str):
        matches = [
            alias
            for alias in source_sets._SOURCE_ALIASES
            if alias.language_code == "ja" and alias.listing_set == listing_set
        ]
        self.assertEqual(len(matches), 1)
        return matches[0]

    @staticmethod
    def _pikachu_coordinate(*, finish: str = "Master Ball"):
        return v1.FanaticsNativeCoordinate(
            year=2023,
            language_code="ja",
            language_label="Japanese",
            set_name="Scarlet & Violet 151",
            name="Pikachu",
            local_id="25",
            grade="10",
            finish=finish,
        )

    @staticmethod
    def _pikachu_canonical():
        # Live Japanese TCGdex labels are localized; the reviewed Fanatics alias
        # deliberately permits that label mismatch only after exact SV2a + #025.
        return canonical.CanonicalCard(
            status="EXACT",
            card_id="SV2a-025",
            set_id="SV2a",
            set_name="ポケモンカード151",
            local_id="025",
            full_number="25/165",
            name="ピカチュウ",
            language_code="ja",
            variants={"normal": True, "reverse": True},
            reason="TCGDEX_EXACT_SET_LOCALID",
        )

    def test_fanatics_numerator_aliases_never_enter_shared_registry(self):
        shared_labels = {
            generalized._norm_text(alias.listing_set)
            for alias in shared_aliases._ALIASES
        }
        for alias in source_sets._SOURCE_ALIASES:
            self.assertNotIn(generalized._norm_text(alias.listing_set), shared_labels)

    def test_source_pinned_numerator_only_namespaces_still_verify_set_count(self):
        cases = (
            ("Scarlet & Violet 151", "SV2a", 165, "25"),
            ("Web 1st Edition", "web1", 48, "47"),
            ("SV Glory Of The Rocket Gang", "SV10", 98, "15"),
        )
        for listing_set, set_id, official_count, local_id in cases:
            with self.subTest(listing_set=listing_set):
                alias = self._alias(listing_set)
                self.assertEqual(alias.tcgdex_set_id, set_id)
                self.assertEqual(alias.tcgdex_official_count, official_count)
                self.assertFalse(alias.require_numeric_denominator)
                self.assertTrue(generalized._validate_reference_for_alias(local_id, alias))
                self.assertTrue(
                    generalized._validate_reference_for_alias(
                        f"{local_id}/{official_count}", alias
                    )
                )
                self.assertFalse(
                    generalized._validate_reference_for_alias(
                        f"{local_id}/{official_count + 1}", alias
                    )
                )

    def test_reviewed_h1_collapses_to_one_deterministic_source_partition(self):
        titles = (
            (
                "2001 Pokemon Japanese Web 1st Edition Holo Gengar #47 PSA 10 GEM MINT",
                "Web 1st Edition",
                "47",
                "Gengar",
            ),
            (
                "2023 Pokemon Japanese Scarlet & Violet 151 Master Ball Reverse Holo Pikachu #025 PSA 10 GEM",
                "Scarlet & Violet 151",
                "25",
                "Pikachu",
            ),
            (
                "2025 Pokemon Japanese SV Glory Of The Rocket Gang Holo Rocket's Moltres ex #15 PSA 9 MINT",
                "SV Glory Of The Rocket Gang",
                "15",
                "Rocket's Moltres ex",
            ),
        )
        for title, expected_set, expected_local, expected_name in titles:
            with self.subTest(title=title):
                base, reason = fanatics._flexible_candidates(title)
                self.assertEqual(reason, "fanatics_flexible_exact_candidates")
                candidates = source_sets._source_candidates(title, base)
                self.assertEqual(len(candidates), 1)
                candidate = candidates[0]
                self.assertEqual(
                    generalized._norm_text(candidate.set_name),
                    generalized._norm_text(expected_set),
                )
                self.assertEqual(candidate.local_id, expected_local)
                self.assertEqual(candidate.name, expected_name)

    def test_unreviewed_or_conflicting_source_phrase_does_not_collapse(self):
        title = "2004 Pokemon Japanese Starter Deck Holo Charizard Ex #12 PSA 10 GEM MINT"
        base, reason = fanatics._flexible_candidates(title)
        self.assertEqual(reason, "fanatics_flexible_exact_candidates")
        self.assertEqual(source_sets._source_candidates(title, base), base)

        conflict = (
            "2023 Pokemon Japanese Scarlet & Violet 151 Web 1st Edition "
            "Holo Pikachu #025 PSA 10 GEM"
        )
        conflict_base, _ = fanatics._flexible_candidates(conflict)
        self.assertEqual(
            source_sets._source_candidates(conflict, conflict_base),
            conflict_base,
        )

    def test_scoped_alias_is_removed_with_all_fanatics_cache_effects(self):
        alias = self._alias("Scarlet & Violet 151")
        coordinate = self._pikachu_coordinate()
        lot = v1._lot_for_coordinate(coordinate)
        alias_key = generalized._alias_key("ja", alias.listing_set)
        *_, cache_key = generalized._lot_components(lot)
        self.assertNotIn(alias_key, generalized._SET_ALIASES_BY_KEY)
        with source_sets._scoped_alias(alias, lot) as installed:
            self.assertTrue(installed)
            self.assertEqual(generalized._SET_ALIASES_BY_KEY.get(alias_key), alias)
            generalized._RECOVERY_CACHE[cache_key] = object()  # type: ignore[assignment]
            generalized._RECOVERY_NEGATIVE_CACHE.add(cache_key)
        self.assertNotIn(alias_key, generalized._SET_ALIASES_BY_KEY)
        self.assertNotIn(cache_key, generalized._RECOVERY_CACHE)
        self.assertNotIn(cache_key, generalized._RECOVERY_NEGATIVE_CACHE)

    def test_scoped_alias_restores_existing_positive_and_negative_after_return_or_abort(self):
        alias = self._alias("Scarlet & Violet 151")
        lot = v1._lot_for_coordinate(self._pikachu_coordinate())
        key = generalized._lot_components(lot)[-1]
        alias_key = generalized._alias_key("ja", alias.listing_set)
        # These sentinels only test state restoration; they never enter a
        # resolver or manufacture a commercial identity.
        old, during = object(), object()
        for abort in (False, True):
            with self.subTest(abort=abort), patch.dict(generalized._RECOVERY_CACHE, {key: old}):
                generalized._RECOVERY_NEGATIVE_CACHE.add(key)
                try:
                    try:
                        with source_sets._scoped_alias(alias, lot):
                            self.assertNotIn(key, generalized._RECOVERY_CACHE)
                            self.assertNotIn(key, generalized._RECOVERY_NEGATIVE_CACHE)
                            generalized._RECOVERY_CACHE[key] = during
                            if abort:
                                raise RuntimeError("source interrupted")
                    except RuntimeError:
                        self.assertTrue(abort)
                    self.assertIs(generalized._RECOVERY_CACHE[key], old)
                    self.assertIn(key, generalized._RECOVERY_NEGATIVE_CACHE)
                    self.assertNotIn(alias_key, generalized._SET_ALIASES_BY_KEY)
                finally:
                    generalized._RECOVERY_NEGATIVE_CACHE.discard(key)

    def test_finish_proof_without_same_card_names_cannot_rewrite_canonical_name(self):
        alias = self._alias("Scarlet & Violet 151")
        coordinate = self._pikachu_coordinate()
        card = self._pikachu_canonical()
        proof = source_finish.SourcePinnedFinishProof(
            finishes=("normal", "reverse"),
            source_path="data-asia/SV/SV2a/025.ts",
            special_finishes=("master_ball",),
        )
        with patch.object(
            source_finish, "source_pinned_finish_proof", return_value=proof
        ) as source_proof, patch.object(
            source_sets, "_ORIGINAL_RESOLVE_COORDINATE"
        ) as downstream:
            recovered = source_sets._resolve_source_special_finish(
                coordinate,
                alias=alias,
                title="provider title",
                proof_text="provider proof",
                resolver=lambda _lot: card,
            )

        self.assertIsNone(recovered)
        downstream.assert_not_called()
        source_card = source_proof.call_args.args[0]
        self.assertEqual(source_card.set_id, "SV2a")
        self.assertEqual(source_card.local_id, "025")
        self.assertEqual(source_card.name, "ピカチュウ")

    def test_master_ball_recovery_fails_closed_on_wrong_source_foil(self):
        alias = self._alias("Scarlet & Violet 151")
        coordinate = self._pikachu_coordinate()
        card = self._pikachu_canonical()
        wrong_proof = source_finish.SourcePinnedFinishProof(
            finishes=("normal", "reverse"),
            source_path="data-asia/SV/SV2a/025.ts",
            special_finishes=("poke_ball",),
            card_names=(("ja", "ピカチュウ"), ("id", "Pikachu")),
        )

        with patch.object(
            source_finish, "source_pinned_finish_proof", return_value=wrong_proof
        ), patch.object(source_sets, "_ORIGINAL_RESOLVE_COORDINATE") as downstream:
            recovered = source_sets._resolve_source_special_finish(
                coordinate,
                alias=alias,
                title="provider title",
                proof_text="provider proof",
                resolver=lambda _lot: card,
            )

        self.assertIsNone(recovered)
        downstream.assert_not_called()

    def test_only_fanatics_aliases_opt_in_to_preserving_catalogue_names(self):
        self.assertTrue(all(alias.preserve_catalog_name for alias in source_sets._SOURCE_ALIASES))
        self.assertFalse(any(alias.preserve_catalog_name for alias in shared_aliases._ALIASES))
        self.assertFalse(any(alias.preserve_catalog_name for alias in generalized._SET_ALIASES))


if __name__ == "__main__":
    unittest.main()
