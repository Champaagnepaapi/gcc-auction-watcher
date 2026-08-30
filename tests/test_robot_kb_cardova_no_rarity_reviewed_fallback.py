from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


PATH = Path("mac/robot-kb-local/robot_kb_cardova_no_rarity_reviewed_fallback.py")
SPEC = importlib.util.spec_from_file_location("cardova_no_rarity_reviewed_fallback", PATH)
fallback = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(fallback)


class ReviewedNoRarityFallbackTests(unittest.TestCase):
    def row(self, name="Sandshrew", number="#027"):
        return {
            "source_native_record_id": "row-1",
            "card_name_provider_claim": name,
            "collector_number_provider_claim": number,
            "provider_set_label": "Pokemon TCG: Japanese Basic",
            "tcgdex_set_id": "PMCG1",
            "pinned_source_commit": fallback.live_probe.SOURCE_COMMIT,
            "provider_opaque_material_tokens": ["no rarity original print"],
            "source_finish_choices": ["normal"],
            "macro_identity_exact": True,
            "microvariant_exact": False,
            "exact_identity_link_candidate": False,
            "printing_exact": False,
            "finish_exact": False,
        }

    def payload(self, rows):
        return {
            "records": rows,
            "blocked": {"PSA_NO_RARITY_HTTP_403": len(rows)},
            "psa_no_rarity_circuit_open": True,
            "macro_identity_exact_count": len(rows),
        }

    def test_manifest_is_exactly_five_reviewed_coordinates(self):
        self.assertEqual(
            set(fallback.REVIEWED_NO_RARITY_EVIDENCE),
            {
                ("sandshrew", 27),
                ("nidorino", 33),
                ("arcanine", 59),
                ("machop", 66),
                ("gastly", 92),
            },
        )

    def test_exact_reviewed_coordinate_can_prove_printing_and_unique_finish(self):
        out = fallback.apply_reviewed_fallback(self.payload([self.row()]))
        row = out["records"][0]
        self.assertTrue(row["printing_exact"])
        self.assertEqual(row["printing"], "no_rarity_symbol")
        self.assertTrue(row["finish_exact"])
        self.assertEqual(row["finish"], "normal")
        self.assertEqual(out["reviewed_no_rarity_rows_proven"], 1)
        self.assertEqual(out["blocked"], {})

    def test_live_psa_403_remains_explicit_after_reviewed_fallback(self):
        out = fallback.apply_reviewed_fallback(self.payload([self.row()]))
        self.assertEqual(out["live_psa_blocked"], {"PSA_NO_RARITY_HTTP_403": 1})
        self.assertTrue(out["psa_no_rarity_circuit_open"])
        self.assertFalse(out["reviewed_no_rarity_cardova_cert_read"])

    def test_wrong_name_or_number_does_not_inherit_reviewed_evidence(self):
        for row in (self.row(name="Pikachu"), self.row(number="#028")):
            out = fallback.apply_reviewed_fallback(self.payload([row]))
            self.assertEqual(out["reviewed_no_rarity_rows_proven"], 0)
            self.assertEqual(out["printing_exact_count"], 0)
            self.assertEqual(
                out["blocked"],
                {"REVIEWED_NO_RARITY_COORDINATE_EVIDENCE_MISSING": 1},
            )

    def test_provider_claim_is_required_exactly(self):
        row = self.row()
        row["provider_opaque_material_tokens"] = ["no rarity"]
        out = fallback.apply_reviewed_fallback(self.payload([row]))
        self.assertEqual(out["reviewed_no_rarity_rows_proven"], 0)
        self.assertFalse(out["records"][0]["printing_exact"])

    def test_non_unique_finish_stays_blocked(self):
        row = self.row()
        row["source_finish_choices"] = ["normal", "holo"]
        out = fallback.apply_reviewed_fallback(self.payload([row]))
        self.assertEqual(out["reviewed_no_rarity_rows_proven"], 0)
        self.assertEqual(
            out["blocked"],
            {"REVIEWED_NO_RARITY_FINISH_NOT_UNIQUE": 1},
        )

    def test_never_promotes_first_edition_microvariant_link_or_commerce(self):
        out = fallback.apply_reviewed_fallback(self.payload([self.row()]))
        row = out["records"][0]
        self.assertFalse(row["edition_exact"])
        self.assertFalse(row["no_rarity_is_first_edition"])
        self.assertFalse(row["microvariant_exact"])
        self.assertFalse(row["exact_identity_link_candidate"])
        self.assertFalse(row["sale_transaction_ready"])
        self.assertFalse(row["v4_economic_use"])
        safety = fallback.safe_summary()
        self.assertFalse(safety["live_psa_403_bypass"])
        self.assertFalse(safety["robot_kb_write"])
        self.assertFalse(safety["automatic_purchase"])
        self.assertFalse(safety["automatic_bid"])
        self.assertFalse(safety["automatic_checkout"])
        self.assertFalse(safety["automatic_payment"])


if __name__ == "__main__":
    unittest.main()
