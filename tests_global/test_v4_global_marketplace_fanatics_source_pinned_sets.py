from __future__ import annotations

import unittest

import v4_global_marketplace_fanatics_native_v3 as fanatics
import v4_tcgdex_generalized_coordinate_recovery as generalized
import v4_tcgdex_japanese_set_aliases as aliases


class FanaticsSourcePinnedJapaneseSetTests(unittest.TestCase):
    def _alias(self, listing_set: str):
        matches = [
            alias
            for alias in aliases._ALIASES
            if alias.language_code == "ja" and alias.listing_set == listing_set
        ]
        self.assertEqual(len(matches), 1)
        return matches[0]

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

    def test_current_fanatics_japanese_h1s_expose_matching_bounded_set_partitions(self):
        titles = (
            ("2001 Pokemon Japanese Web 1st Edition Holo Gengar #47 PSA 10 GEM MINT", "Web 1st Edition", "47"),
            ("2023 Pokemon Japanese Scarlet & Violet 151 Master Ball Reverse Holo Pikachu #025 PSA 10 GEM", "Scarlet & Violet 151", "25"),
            ("2025 Pokemon Japanese SV Glory Of The Rocket Gang Holo Rocket's Moltres ex #15 PSA 9 MINT", "SV Glory Of The Rocket Gang", "15"),
        )
        for title, expected_set, expected_local in titles:
            with self.subTest(title=title):
                candidates, reason = fanatics._flexible_candidates(title)
                self.assertEqual(reason, "fanatics_flexible_exact_candidates")
                matching = [
                    candidate
                    for candidate in candidates
                    if generalized._norm_text(candidate.set_name)
                    == generalized._norm_text(expected_set)
                    and candidate.local_id == expected_local
                ]
                self.assertTrue(matching)


if __name__ == "__main__":
    unittest.main()
