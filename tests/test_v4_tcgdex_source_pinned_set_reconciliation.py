from __future__ import annotations

import unittest
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as canonical
import v4_multimarket_safety as safety
import v4_tcgdex_generalized_coordinate_recovery as generalized
import v4_tcgdex_japanese_set_aliases as japanese_aliases
import v4_tcgdex_source_pinned_finish as source_finish
import v4_tcgdex_source_pinned_set_reconciliation as reconciliation


class _Response:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class SourcePinnedSetReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.original_aliases = generalized._SET_ALIASES
        self.original_by_key = dict(generalized._SET_ALIASES_BY_KEY)
        japanese_aliases.install_v4_tcgdex_japanese_set_aliases()
        source_finish.clear_source_finish_runtime_state()
        canonical._DIAGNOSTICS = canonical.MultiMarketDiagnostics()

    def tearDown(self):
        generalized._SET_ALIASES = self.original_aliases
        generalized._SET_ALIASES_BY_KEY.clear()
        generalized._SET_ALIASES_BY_KEY.update(self.original_by_key)
        source_finish.clear_source_finish_runtime_state()

    @staticmethod
    def _lot(
        number: str = "117/098",
        *,
        title: str = "Team Rocket's Crobat Ex",
    ) -> watcher.Lot:
        return watcher.Lot(
            url="https://gradedcardcenter.com/item/team-rocket-source-set-test",
            title=title,
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
    def _wrong_rest_card(
        *,
        number: str = "117/098",
        title: str = "Team Rocket's Crobat Ex",
    ) -> canonical.CanonicalCard:
        local_id = number.split("/", 1)[0]
        return canonical.CanonicalCard(
            status="EXACT",
            card_id=f"S12-{local_id}",
            set_id="S12",
            set_name="Glory of the Team Rocket",
            local_id=local_id,
            full_number=number,
            name=title,
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

    @staticmethod
    def _source(set_id: str, *finishes: str) -> str:
        variants = "\n".join(
            f'        {{ type: "{finish}", thirdParty: {{ cardmarket: 1 }} }},'
            for finish in finishes
        )
        return (
            'import { Card } from "../../../interfaces";\n'
            f'import Set from "../{set_id}";\n'
            "const card: Card = {\n"
            "    variants: [\n"
            f"{variants}\n"
            "    ],\n"
            "};\n"
            "export default card;\n"
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

    def test_stale_rest_namespace_falls_back_to_immutable_crobat_source(self):
        lot = self._lot()
        with patch.object(generalized, "_fetch_coordinate", return_value=None), patch.object(
            source_finish._SESSION,
            "get",
            return_value=_Response(200, self._source("SV10", "holo")),
        ) as get:
            result = reconciliation._reconcile_exact_source_pinned_set(
                lot, self._wrong_rest_card()
            )

        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "SV10-117")
        self.assertEqual(result.set_id, "SV10")
        self.assertEqual(result.local_id, "117")
        self.assertEqual(result.full_number, "117/098")
        self.assertEqual(result.reason, "TCGDEX_SOURCE_PINNED_SET_RECONCILED")
        self.assertFalse(result.variants["normal"])
        self.assertTrue(result.variants["holo"])
        self.assertFalse(result.variants["reverse"])
        self.assertEqual(get.call_count, 1)
        self.assertIn("/data-asia/SV/SV10/117.ts", get.call_args.args[0])

    def test_live_houndoom_failure_class_is_recovered_from_same_source_rule(self):
        lot = self._lot("100/098", title="Team Rocket's Houndoom")
        wrong = self._wrong_rest_card(
            number="100/098", title="Team Rocket's Houndoom"
        )
        with patch.object(generalized, "_fetch_coordinate", return_value=None), patch.object(
            source_finish._SESSION,
            "get",
            return_value=_Response(200, self._source("SV10", "holo")),
        ) as get:
            result = reconciliation._reconcile_exact_source_pinned_set(lot, wrong)

        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "SV10-100")
        self.assertEqual(result.set_id, "SV10")
        self.assertEqual(result.name, "Team Rocket's Houndoom")
        self.assertTrue(result.variants["holo"])
        self.assertEqual(get.call_count, 1)
        self.assertIn("/data-asia/SV/SV10/100.ts", get.call_args.args[0])

    def test_unprovable_conflicting_namespace_blocks_fail_closed(self):
        lot = self._lot()
        canonical._DIAGNOSTICS.tcgdex_exact = 1
        with patch.object(generalized, "_fetch_coordinate", return_value=None), patch.object(
            source_finish, "source_pinned_finish_proof", return_value=None
        ):
            result = reconciliation._reconcile_exact_source_pinned_set(
                lot, self._wrong_rest_card()
            )

        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertIn("S12 != SV10", result.reason)
        self.assertEqual(canonical._DIAGNOSTICS.tcgdex_exact, 0)
        self.assertEqual(canonical._DIAGNOSTICS.tcgdex_ambiguous, 1)

    def test_wrong_source_set_import_cannot_reconcile(self):
        lot = self._lot()
        canonical._DIAGNOSTICS.tcgdex_exact = 1
        with patch.object(generalized, "_fetch_coordinate", return_value=None), patch.object(
            source_finish._SESSION,
            "get",
            return_value=_Response(200, self._source("S12", "holo")),
        ):
            result = reconciliation._reconcile_exact_source_pinned_set(
                lot, self._wrong_rest_card()
            )

        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(canonical._DIAGNOSTICS.tcgdex_exact, 0)
        self.assertEqual(canonical._DIAGNOSTICS.tcgdex_ambiguous, 1)

    def test_wrong_denominator_does_not_override_an_exact_result(self):
        lot = self._lot("117/097")
        with patch.object(
            generalized,
            "_fetch_coordinate",
            side_effect=AssertionError("wrong denominator must not reconcile"),
        ), patch.object(
            source_finish,
            "source_pinned_finish_proof",
            side_effect=AssertionError("wrong denominator must not reach source"),
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
