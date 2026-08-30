from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


PATH = Path("mac/robot-kb-local/robot_kb_cardova_legacy_microvariant_closure_probe.py")
SPEC = importlib.util.spec_from_file_location("cardova_legacy_microvariant_closure", PATH)
probe = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(probe)


class LegacyMicrovariantClosureTests(unittest.TestCase):
    def row(self, *, finish="normal", set_id="neo1", local_id="001"):
        return {
            "source_native_record_id": "row-1",
            "card_name_provider_claim": "Example",
            "collector_number_provider_claim": "#001",
            "provider_set_label": "Example Set",
            "grader": "PSA",
            "grade": "9",
            "tcgdex_card_id": f"{set_id}-{local_id}",
            "tcgdex_set_id": set_id,
            "tcgdex_local_id": local_id,
            "pinned_source_path": f"data-asia/neo/{set_id}/{local_id}.ts",
            "pinned_source_commit": probe.SOURCE_COMMIT,
            "source_finish_choices": [finish],
            "provider_finish_state": "ABSENT",
            "provider_finish_claim": "",
            "provider_opaque_material_tokens": [],
            "finish_exact": True,
            "finish": finish,
            "finish_proof_reason": "FINISH_EXACT_UNIQUE_PINNED_SOURCE",
            "commercial_axes_proven": {"finish": finish},
            "macro_identity_exact": True,
            "printing_exact": False,
            "edition_exact": False,
            "microvariant_exact": False,
            "exact_identity_link_candidate": False,
        }

    def source(self, variants, *, set_id="neo1"):
        return f'''import {{ Card }} from "../../../interfaces"
import Set from "../{set_id}"
const card: Card = {{
  set: Set,
  variants: [
{variants}
  ],
}};
export default card
'''

    def close(self, row, source):
        return probe.close_record(row, source_fetcher=lambda _path: source)

    def test_unique_normal_variant_closes_all_applicability_axes(self):
        row, reason = self.close(
            self.row(),
            self.source('    { type: "normal" },'),
        )
        self.assertEqual(reason, "MICROVARIANT_EXACT_UNIQUE_PINNED_SOURCE_VARIANT")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertTrue(row["microvariant_exact"])
        self.assertTrue(row["exact_identity_link_candidate"])
        self.assertTrue(row["edition_applicability_exact"])
        self.assertFalse(row["edition_exact"])
        self.assertEqual(
            row["edition_applicability_reason"],
            "NOT_APPLICABLE_IN_PINNED_SOURCE_VARIANT",
        )
        self.assertTrue(row["special_finish_applicability_exact"])
        self.assertFalse(row["special_finish_exact"])
        self.assertTrue(row["variant_applicability_exact"])
        self.assertEqual(row["remaining_unproven_axes"], [])
        self.assertFalse(row["canonical_link_written"])

    def test_ordinary_plus_no_rarity_without_positive_printing_stays_ambiguous(self):
        source = self.source(
            '''    { type: "normal" },
    { type: "normal", subtype: "no-rarity" },'''
        )
        row, reason = self.close(self.row(), source)
        self.assertIsNone(row)
        self.assertEqual(reason, "PINNED_SOURCE_VARIANT_AMBIGUOUS")

    def test_positive_reviewed_no_rarity_selects_only_no_rarity_source_variant(self):
        row = self.row()
        row.update(
            {
                "provider_opaque_material_tokens": ["no rarity original print"],
                "provider_no_rarity_claim_exact": True,
                "printing_exact": True,
                "printing": "no_rarity_symbol",
                "commercial_axes_proven": {
                    "finish": "normal",
                    "printing": "no_rarity_symbol",
                },
            }
        )
        source = self.source(
            '''    { type: "normal" },
    { type: "normal", subtype: "no-rarity" },'''
        )
        closed, reason = self.close(row, source)
        self.assertEqual(reason, "MICROVARIANT_EXACT_UNIQUE_PINNED_SOURCE_VARIANT")
        self.assertIsNotNone(closed)
        assert closed is not None
        self.assertTrue(closed["microvariant_exact"])
        self.assertTrue(closed["printing_exact"])
        self.assertEqual(closed["printing"], "no_rarity_symbol")
        self.assertEqual(
            closed["pinned_source_variant_dimensions"]["printing"],
            "no_rarity_symbol",
        )
        self.assertFalse(closed.get("no_rarity_is_first_edition", False))

    def test_unknown_material_subtype_is_opaque_and_blocking(self):
        row, reason = self.close(
            self.row(),
            self.source('    { type: "normal", subtype: "mystery-print" },'),
        )
        self.assertIsNone(row)
        self.assertEqual(reason, "PINNED_SOURCE_VARIANT_OPAQUE")

    def test_finish_conflict_blocks(self):
        row, reason = self.close(
            self.row(finish="holo"),
            self.source('    { type: "normal" },'),
        )
        self.assertIsNone(row)
        self.assertEqual(reason, "PINNED_SOURCE_VARIANT_CONFLICT")

    def test_wrong_pinned_commit_or_coordinate_blocks_before_source_use(self):
        bad_commit = self.row()
        bad_commit["pinned_source_commit"] = "deadbeef"
        row, reason = self.close(bad_commit, self.source('    { type: "normal" },'))
        self.assertIsNone(row)
        self.assertEqual(reason, "PINNED_SOURCE_COMMIT_CONFLICT")

        bad_path = self.row()
        bad_path["pinned_source_path"] = "data-asia/neo/neo1/999.ts"
        row, reason = self.close(bad_path, self.source('    { type: "normal" },'))
        self.assertIsNone(row)
        self.assertEqual(reason, "PINNED_SOURCE_COORDINATE_CONFLICT")

    def test_unresolved_provider_material_token_blocks(self):
        row = self.row()
        row["provider_opaque_material_tokens"] = ["sr"]
        closed, reason = self.close(row, self.source('    { type: "normal" },'))
        self.assertIsNone(closed)
        self.assertEqual(reason, "PROVIDER_MATERIAL_TOKEN_UNRESOLVED")

    def test_no_rarity_provider_token_without_independent_printing_proof_blocks(self):
        row = self.row()
        row["provider_opaque_material_tokens"] = ["no rarity original print"]
        closed, reason = self.close(
            row,
            self.source('    { type: "normal", subtype: "no-rarity" },'),
        )
        self.assertIsNone(closed)
        self.assertEqual(reason, "PROVIDER_MATERIAL_TOKEN_UNRESOLVED")

    def test_v4_detailed_semantics_are_reused_for_edition_and_special_finish(self):
        source = self.source(
            '    { type: "holo", stamp: "1st-edition", foil: "cosmos", thirdParty: { tcgplayer: 1 } },'
        )
        closed, reason = self.close(self.row(finish="holo"), source)
        self.assertEqual(reason, "MICROVARIANT_EXACT_UNIQUE_PINNED_SOURCE_VARIANT")
        self.assertIsNotNone(closed)
        assert closed is not None
        self.assertTrue(closed["edition_exact"])
        self.assertEqual(closed["edition"], "first_edition")
        self.assertTrue(closed["special_finish_exact"])
        self.assertEqual(closed["special_finish"], "cosmos")
        self.assertEqual(
            closed["pinned_source_variant_dimensions"],
            {
                "edition": "first_edition",
                "finish": "holo",
                "special_finish": "cosmos",
            },
        )

    def test_unknown_top_level_source_field_is_opaque(self):
        closed, reason = self.close(
            self.row(),
            self.source('    { type: "normal", mysteryField: "x" },'),
        )
        self.assertIsNone(closed)
        self.assertEqual(reason, "PINNED_SOURCE_VARIANT_OPAQUE")

    def test_safety_contract_keeps_all_mutations_and_commerce_off(self):
        safety = probe.safe_summary()
        self.assertTrue(safety["v4_detailed_variant_semantics_reused"])
        self.assertFalse(safety["psa_live_refetch"])
        self.assertFalse(safety["canonical_link_written"])
        self.assertFalse(safety["robot_kb_write"])
        self.assertFalse(safety["sale_transaction_ready"])
        self.assertFalse(safety["v4_economic_use"])
        self.assertFalse(safety["automatic_purchase"])
        self.assertFalse(safety["automatic_bid"])
        self.assertFalse(safety["automatic_offer"])
        self.assertFalse(safety["automatic_checkout"])
        self.assertFalse(safety["automatic_payment"])


if __name__ == "__main__":
    unittest.main()
