from __future__ import annotations

import unittest
from unittest import mock

import watcher
import v4_canonical_multimarket as multimarket
import v4_poketrace_market_retrieval as poketrace
import v4_tcgdex_generalized_coordinate_recovery as generalized
import v4_tcgdex_japanese_set_aliases as aliases


class GlobalLiveGapRecoveryTests(unittest.TestCase):
    @staticmethod
    def _alias(label: str) -> generalized.ExactSetAlias:
        matches = [alias for alias in aliases._ALIASES if alias.listing_set == label]
        if len(matches) != 1:
            raise AssertionError(f"expected one alias for {label!r}, got {len(matches)}")
        return matches[0]

    def test_inferno_x_alias_is_exact_numeric_coordinate(self):
        alias = self._alias("Inferno X")
        self.assertEqual(alias.tcgdex_set_id, "M2")
        self.assertEqual(alias.tcgdex_official_count, 80)
        self.assertTrue(alias.require_numeric_denominator)
        self.assertTrue(generalized._validate_reference_for_alias("111/80", alias))
        self.assertFalse(generalized._validate_reference_for_alias("111/81", alias))

    def test_s_p_promo_alias_requires_exact_namespace_suffix(self):
        alias = self._alias("S-P Promotional")
        self.assertEqual(alias.tcgdex_set_id, "S-P")
        self.assertEqual(alias.tcgdex_official_count, 0)
        self.assertTrue(generalized._validate_reference_for_alias("214/S-P", alias))
        self.assertFalse(generalized._validate_reference_for_alias("214/SV-P", alias))

    def test_sv_p_promo_alias_covers_both_measured_coordinates(self):
        alias = self._alias("SV-P Promos")
        self.assertEqual(alias.tcgdex_set_id, "SV-P")
        self.assertEqual(alias.tcgdex_official_count, 0)
        self.assertTrue(generalized._validate_reference_for_alias("1/SV-P", alias))
        self.assertTrue(generalized._validate_reference_for_alias("242/SV-P", alias))
        self.assertFalse(generalized._validate_reference_for_alias("242/S-P", alias))

    def test_missing_s8a_p_catalog_gap_is_not_fabricated(self):
        labels = {alias.listing_set for alias in aliases._ALIASES}
        self.assertNotIn("25th Anniversary Collection - Promo", labels)

    def test_poketrace_diagnostic_distinguishes_set_gate_without_relaxing(self):
        lot = watcher.Lot(
            url="https://example.invalid/oricorio",
            title="Oricorio Ex",
            current_price=50.0,
            source_type="fixed",
            grader="PSA",
            grade="10",
            card_number="111/80",
            card_set="Inferno X",
            language="Japanese",
        )
        canonical = multimarket.CanonicalCard(
            "EXACT",
            card_id="M2-111",
            set_id="M2",
            set_name="Inferno X",
            local_id="111",
            full_number="111/80",
            name="Oricorio Ex",
            language_code="ja",
            variants={},
            reason="TCGDEX_EXACT_SET_LOCALID",
        )
        candidate = {
            "id": "pt-oricorio",
            "name": "Oricorio ex",
            "cardNumber": "111/80",
            "set": {"name": "Wrong Set"},
            "productType": "single",
            "game": "pokemon-japanese",
        }
        with mock.patch.object(
            multimarket, "_candidate_exact_for_canonical", return_value=False
        ):
            reason = poketrace._diagnostic_rejection_reason(
                lot, canonical, candidate
            )
        self.assertEqual(reason, "REJECT_SET")


if __name__ == "__main__":
    unittest.main()
