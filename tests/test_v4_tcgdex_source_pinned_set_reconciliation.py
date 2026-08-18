from __future__ import annotations

import unittest
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as canonical
import v4_multimarket_safety as safety
import v4_tcgdex_generalized_coordinate_recovery as generalized
import v4_tcgdex_japanese_set_aliases as japanese_aliases
import v4_tcgdex_source_pinned_set_reconciliation as reconciliation


class SourcePinnedSetReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.original_aliases = generalized._SET_ALIASES
        self.original_by_key = dict(generalized._SET_ALIASES_BY_KEY)
        japanese_aliases.install_v4_tcgdex_japanese_set_aliases()
        canonical._DIAGNOSTICS = canonical.MultiMarketDiagnostics()

    def tearDown(self):
        generalized._SET_ALIASES = self.original_aliases
        generalized._SET_ALIASES_BY_KEY.clear()
        generalized._SET_ALIASES_BY_KEY.update(self.original_by_key)

    @staticmethod
    def _lot(number: str = "117/098") -> watcher.Lot:
        return watcher.Lot(
            url="https://gradedcardcenter.com/item/team-rocket-crobat-test",
            title="Team Rocket's Crobat Ex",
            current_price=50.0,
            source_type="fixed",
            grader="PSA",
            grade="9",
            card_number=number,
            card_set="Glory of the Team Rocket",
            language="Japanese",
            body=(
                "Catégorie: Pokémon\n"
                f"Référence: #{number}\n"
                "Série: Glory of the Team Rocket\n"
                "Langue: Japanese\n"
            ),
        )

    @staticmethod
    def _wrong_rest_card() -> canonical.CanonicalCard:
        return canonical.CanonicalCard(
            status="EXACT",
            card_id="S12-117",
            set_id="S12",
            set_name="Glory of the Team Rocket",
            local_id="117",
            full_number="117/098",
            name="Team Rocket's Crobat Ex",
            language_code="ja",
            variants={"normal": True, "holo": False, "reverse": False},
            reason="TCGDEX_EXACT",
        )

    @staticmethod
    def _source_pinned_card() -> canonical.CanonicalCard:
        return canonical.CanonicalCard(
            status="EXACT",
            card_id="SV10-117",
            set_id="SV10",
            set_name="Glory of the Team Rocket",
            local_id="117",
            full_number="117/098",
            name="Team Rocket's Crobat Ex",
            language_code="ja",
            variants={"normal": False, "holo": True, "reverse": False},
            reason="TCGDEX_EXACT_SET_LOCALID",
        )

    def test_glory_of_team_rocket_alias_is_source_pinned_sv10(self):
        key = generalized._alias_key("ja", "Glory of the Team Rocket")
        alias = generalized._SET_ALIASES_BY_KEY[key]
        self.assertEqual(alias.tcgdex_set_id, "SV10")
        self.assertEqual(alias.tcgdex_official_count, 98)
        self.assertTrue(alias.require_numeric_denominator)
        self.assertTrue(alias.allow_localized_name_mismatch)

    def test_conflicting_exact_rest_namespace_is_reconciled_to_sv10(self):
        lot = self._lot()
        corrected = self._source_pinned_card()
        with patch.object(generalized, "_fetch_coordinate", return_value=corrected) as fetch:
            result = reconciliation._reconcile_exact_source_pinned_set(
                lot, self._wrong_rest_card()
            )

        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "SV10-117")
        self.assertEqual(result.set_id, "SV10")
        self.assertEqual(result.reason, "TCGDEX_SOURCE_PINNED_SET_RECONCILED")
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.kwargs["set_id"], "SV10")
        self.assertEqual(fetch.call_args.kwargs["expected_count"], 98)

    def test_unprovable_conflicting_namespace_blocks_fail_closed(self):
        lot = self._lot()
        canonical._DIAGNOSTICS.tcgdex_exact = 1
        with patch.object(generalized, "_fetch_coordinate", return_value=None):
            result = reconciliation._reconcile_exact_source_pinned_set(
                lot, self._wrong_rest_card()
            )

        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertIn("S12 != SV10", result.reason)
        self.assertEqual(canonical._DIAGNOSTICS.tcgdex_exact, 0)
        self.assertEqual(canonical._DIAGNOSTICS.tcgdex_ambiguous, 1)

    def test_wrong_denominator_does_not_override_an_exact_result(self):
        lot = self._lot("117/097")
        with patch.object(
            generalized,
            "_fetch_coordinate",
            side_effect=AssertionError("wrong denominator must not reconcile"),
        ):
            result = reconciliation._reconcile_exact_source_pinned_set(
                lot, self._wrong_rest_card()
            )
        self.assertEqual(result.set_id, "S12")

    def test_reconciled_live_shape_passes_existing_poketrace_set_and_finish_gates(self):
        lot = self._lot()
        corrected = self._source_pinned_card()
        provider = {
            "productType": "single",
            "name": "Team Rocket's Crobat ex (Japanese)",
            "cardNumber": "117/098",
            "set": {"name": "SV10: The Glory of Team Rocket"},
            "game": "pokemon-japanese",
            "variant": "Holofoil",
        }
        self.assertTrue(
            safety.hardened_candidate_exact_for_canonical(lot, corrected, provider)
        )


if __name__ == "__main__":
    unittest.main()
