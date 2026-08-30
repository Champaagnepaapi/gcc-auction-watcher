from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


PATH = Path("mac/robot-kb-local/robot_kb_cardova_public_title_printing_proof.py")
SPEC = importlib.util.spec_from_file_location("cardova_public_title_printing_proof", PATH)
probe = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(probe)


class CardovaPublicTitlePrintingProofTests(unittest.TestCase):
    def row(
        self,
        *,
        source_id="01KFFRJ8B4X9FG8YK90K4BNS1T",
        name="Ninetales",
        grade="10",
        finish="holo",
    ):
        return {
            "source_native_record_id": source_id,
            "card_name_provider_claim": name,
            "grade": grade,
            "tcgdex_set_id": "PMCG1",
            "macro_identity_exact": True,
            "finish_exact": True,
            "finish": finish,
            "printing_exact": False,
            "commercial_axes_proven": {"finish": finish},
        }

    def test_exact_no_rarity_title_proves_printing_only(self):
        row = self.row()
        url = "https://www.cardova.co.jp/en/auction/card/01KFFRJ8B4X9FG8YK90K4BNS1T"
        out, reason = probe.prove_title(
            row,
            page_url=url,
            page_title=(
                "1996 Ninetales PSA 10 Holo No Rarity Original Print - Cardova Japan"
            ),
        )
        self.assertEqual(reason, "PRINTING_EXACT_CARDOVA_PUBLIC_TITLE_NO_RARITY")
        self.assertIsNotNone(out)
        assert out is not None
        self.assertTrue(out["printing_exact"])
        self.assertEqual(out["printing"], "no_rarity_symbol")
        self.assertFalse(out["no_rarity_is_first_edition"])
        self.assertFalse(out["microvariant_exact"])
        self.assertFalse(out["sale_transaction_ready"])

    def test_error_strength_tail_is_material_and_blocks_plain_no_rarity(self):
        row = self.row(
            source_id="01KQHACBX20NBMGD9VZAPA6Z64",
            name="Charizard",
            grade="8",
        )
        out, reason = probe.prove_title(
            row,
            page_url=(
                "https://www.cardova.co.jp/en/auction/card/01KQHACBX20NBMGD9VZAPA6Z64"
            ),
            page_title=(
                "1996 Charizard PSA 8 Holo No Rarity Original Print "
                "Error(Strength) - Cardova Japan"
            ),
        )
        self.assertEqual(reason, "CARDOVA_PUBLIC_TITLE_MATERIAL_TAIL_UNRESOLVED")
        self.assertIsNotNone(out)
        assert out is not None
        self.assertFalse(out["printing_exact"])
        self.assertEqual(out["cardova_public_material_tail"], "Error(Strength)")
        self.assertFalse(out["exact_identity_link_candidate"])

    def test_plain_title_never_proves_standard_printing(self):
        row = self.row(
            source_id="01KZ5VB9KH7573R44RMZSQ6AW8",
            name="Venusaur",
            grade="9",
        )
        out, reason = probe.prove_title(
            row,
            page_url=(
                "https://www.cardova.co.jp/en/auction/card/01KZ5VB9KH7573R44RMZSQ6AW8"
            ),
            page_title="1996 Venusaur PSA 9 Holo - Cardova Japan",
        )
        self.assertIsNone(out)
        self.assertEqual(reason, "CARDOVA_PUBLIC_TITLE_NO_PRINTING_PROOF")

    def test_card_identity_conflict_blocks(self):
        row = self.row()
        out, reason = probe.prove_title(
            row,
            page_url=(
                "https://www.cardova.co.jp/en/auction/card/01KFFRJ8B4X9FG8YK90K4BNS1T"
            ),
            page_title=(
                "1996 Charizard PSA 10 Holo No Rarity Original Print - Cardova Japan"
            ),
        )
        self.assertIsNone(out)
        self.assertEqual(reason, "CARDOVA_PUBLIC_TITLE_IDENTITY_CONFLICT")

    def test_source_native_url_conflict_blocks(self):
        row = self.row()
        out, reason = probe.prove_title(
            row,
            page_url=(
                "https://www.cardova.co.jp/en/auction/card/01KQHACBX20NBMGD9VZAPA6Z64"
            ),
            page_title=(
                "1996 Ninetales PSA 10 Holo No Rarity Original Print - Cardova Japan"
            ),
        )
        self.assertIsNone(out)
        self.assertEqual(reason, "CARDOVA_PUBLIC_URL_CONFLICT")

    def test_safety_contract(self):
        safety = probe.safe_summary()
        self.assertFalse(safety["absence_proves_standard_printing"])
        self.assertTrue(safety["material_tail_blocks_plain_no_rarity"])
        self.assertFalse(safety["no_rarity_is_first_edition"])
        self.assertFalse(safety["robot_kb_write"])
        self.assertFalse(safety["v4_economic_use"])
        self.assertFalse(safety["automatic_purchase"])
        self.assertFalse(safety["automatic_bid"])
        self.assertFalse(safety["automatic_checkout"])
        self.assertFalse(safety["automatic_payment"])


if __name__ == "__main__":
    unittest.main()
