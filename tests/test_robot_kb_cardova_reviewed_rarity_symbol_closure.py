from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


PROOF_PATH = Path("mac/robot-kb-local/robot_kb_cardova_reviewed_rarity_symbol_proof.py")
PROOF_SPEC = importlib.util.spec_from_file_location("cardova_reviewed_rarity_symbol_proof", PROOF_PATH)
proof = importlib.util.module_from_spec(PROOF_SPEC)
assert PROOF_SPEC.loader is not None
PROOF_SPEC.loader.exec_module(proof)

CLOSURE_PATH = Path("mac/robot-kb-local/robot_kb_cardova_rarity_symbol_microvariant_closure.py")
CLOSURE_SPEC = importlib.util.spec_from_file_location("cardova_rarity_symbol_closure", CLOSURE_PATH)
closure = importlib.util.module_from_spec(CLOSURE_SPEC)
assert CLOSURE_SPEC.loader is not None
CLOSURE_SPEC.loader.exec_module(closure)


class ReviewedRaritySymbolClosureTests(unittest.TestCase):
    def row(self, source_id: str):
        e = proof.REVIEWED_RARITY_SYMBOL_EVIDENCE[source_id]
        return {
            "source_native_record_id": source_id,
            "card_name_provider_claim": e["card"],
            "collector_number_provider_claim": "#000",
            "provider_set_label": "Pokemon TCG: Japanese Basic",
            "grader": "PSA",
            "grade": e["grade"],
            "tcgdex_card_id": f"PMCG1-{e['local_id']}",
            "tcgdex_set_id": "PMCG1",
            "tcgdex_local_id": e["local_id"],
            "pinned_source_path": f"data-asia/sets/PMCG1/{e['local_id']}.ts",
            "pinned_source_commit": closure.base.SOURCE_COMMIT,
            "source_finish_choices": [e["finish"]],
            "provider_finish_state": "EXACT" if e["finish"] == "holo" else "ABSENT",
            "provider_finish_claim": "Holo" if e["finish"] == "holo" else "",
            "provider_opaque_material_tokens": [],
            "finish_exact": True,
            "finish": e["finish"],
            "finish_proof_reason": "TEST_FINISH_EXACT",
            "commercial_axes_proven": {"finish": e["finish"]},
            "macro_identity_exact": True,
            "printing_exact": False,
            "edition_exact": False,
            "microvariant_exact": False,
            "exact_identity_link_candidate": False,
        }

    def source(self, finish: str, *, third_variant: bool = False):
        t = "holo" if finish == "holo" else "normal"
        extra = '\n    { type: "reverse" },' if third_variant else ""
        return f'''import {{ Card }} from "../../../interfaces"
import Set from "../PMCG1"
const card: Card = {{
  set: Set,
  variants: [
    {{ type: "{t}" }},
    {{ type: "{t}", subtype: "no-rarity" }},{extra}
  ],
}};
export default card
'''

    def apply(self, row):
        e = proof.REVIEWED_RARITY_SYMBOL_EVIDENCE[row["source_native_record_id"]]
        return proof.apply_reviewed_front_image_proof(
            row,
            certificate_number=e["cert"],
            image_a=e["image_a"],
            image_sha256=e["image_sha256"],
        )

    def test_manifest_is_exactly_ten_reviewed_rows(self):
        self.assertEqual(len(proof.REVIEWED_RARITY_SYMBOL_EVIDENCE), 10)
        self.assertEqual(
            {e["symbol"] for e in proof.REVIEWED_RARITY_SYMBOL_EVIDENCE.values()},
            {"star", "circle"},
        )

    def test_all_ten_reviewed_rows_close_ordinary_variant(self):
        for source_id, evidence in proof.REVIEWED_RARITY_SYMBOL_EVIDENCE.items():
            with self.subTest(source_id=source_id):
                row = self.row(source_id)
                proved, reason = self.apply(row)
                self.assertEqual(reason, proof.PROOF_REASON)
                self.assertIsNotNone(proved)
                assert proved is not None
                self.assertTrue(proof.has_exact_no_rarity_exclusion(proved))

                closed, close_reason = closure.close_record(
                    proved,
                    source_fetcher=lambda _path, f=evidence["finish"]: self.source(f),
                )
                self.assertEqual(
                    close_reason,
                    "MICROVARIANT_EXACT_VISIBLE_RARITY_SYMBOL_EXCLUDES_NO_RARITY",
                )
                self.assertIsNotNone(closed)
                assert closed is not None
                self.assertTrue(closed["microvariant_exact"])
                self.assertTrue(closed["exact_identity_link_candidate"])
                self.assertFalse(closed["printing_exact"])
                self.assertEqual(closed["printing"], "")
                self.assertTrue(closed["printing_applicability_exact"])
                self.assertEqual(
                    closed["printing_applicability_reason"],
                    "NO_RARITY_EXCLUDED_BY_REVIEWED_VISIBLE_RARITY_SYMBOL",
                )
                self.assertNotIn("printing", closed["pinned_source_variant_dimensions"])
                self.assertFalse(closed["canonical_link_written"])
                self.assertFalse(closed["sale_transaction_ready"])

    def test_bad_image_hash_never_creates_exclusion(self):
        source_id = "01KZ5VB9KH7573R44RMZSQ6AW8"
        row = self.row(source_id)
        e = proof.REVIEWED_RARITY_SYMBOL_EVIDENCE[source_id]
        proved, reason = proof.apply_reviewed_front_image_proof(
            row,
            certificate_number=e["cert"],
            image_a=e["image_a"],
            image_sha256="0" * 64,
        )
        self.assertIsNone(proved)
        self.assertEqual(reason, "REVIEWED_RARITY_SYMBOL_IMAGE_HASH_CONFLICT")

    def test_unreviewed_boolean_cannot_select_ordinary_variant(self):
        source_id = "01KZ5VB9KH7573R44RMZSQ6AW8"
        row = self.row(source_id)
        row["no_rarity_symbol_excluded_exact"] = True
        row["reviewed_rarity_symbol_visible_exact"] = True
        closed, reason = closure.close_record(
            row,
            source_fetcher=lambda _path: self.source("holo"),
        )
        self.assertIsNone(closed)
        self.assertEqual(reason, "PINNED_SOURCE_VARIANT_AMBIGUOUS")

    def test_shape_must_be_only_ordinary_vs_no_rarity(self):
        source_id = "01KZ5VB9KH7573R44RMZSQ6AW8"
        row = self.row(source_id)
        proved, _ = self.apply(row)
        assert proved is not None
        closed, reason = closure.close_record(
            proved,
            source_fetcher=lambda _path: self.source("holo", third_variant=True),
        )
        # Reverse does not match the exact holo finish, so the compatible shape
        # remains exactly ordinary-vs-No-Rarity and still closes safely.
        self.assertIsNotNone(closed)
        self.assertEqual(
            reason,
            "MICROVARIANT_EXACT_VISIBLE_RARITY_SYMBOL_EXCLUDES_NO_RARITY",
        )

    def test_no_rarity_control_is_not_in_ordinary_manifest(self):
        self.assertNotIn(
            "01KFFRJ8B4X9FG8YK90K4BNS1T",
            proof.REVIEWED_RARITY_SYMBOL_EVIDENCE,
        )

    def test_safety_contract(self):
        safety = closure.safe_summary()
        self.assertTrue(safety["positive_visible_symbol_required"])
        self.assertFalse(safety["absence_of_provider_text_proves_standard"])
        self.assertFalse(safety["synthetic_standard_printing_value_created"])
        self.assertFalse(safety["images_stored_in_repo"])
        self.assertTrue(safety["base_legacy_closure_reused"])
        self.assertFalse(safety["canonical_link_written"])
        self.assertFalse(safety["robot_kb_write"])
        self.assertFalse(safety["sale_transaction_ready"])
        self.assertFalse(safety["v4_economic_use"])
        self.assertFalse(safety["automatic_purchase"])
        self.assertFalse(safety["automatic_bid"])
        self.assertFalse(safety["automatic_checkout"])
        self.assertFalse(safety["automatic_payment"])


if __name__ == "__main__":
    unittest.main()
