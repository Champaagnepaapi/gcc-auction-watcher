from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "mac" / "robot-kb-local"
for candidate in (ROOT, LOCAL):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_bounded_macro_identity_probe as probe


COHORT_STATUS = "SOURCE_PINNED_COHORT_SET_DEXID_NAME_GATED_CANDIDATE_ONLY"
SET_STATUS = "PSA_REGISTRY_AND_PINNED_SET_CORROBORATED_CANDIDATE_ONLY"


def row(native: str, dex_id: int, card_id: str, local_id: str):
    return {
        "source_native_record_id": native,
        "card_name_provider_claim": "Charizard" if dex_id == 6 else "Blastoise",
        "collector_number_provider_claim": f"#{dex_id:03d}",
        "set_name_provider_claim": "Pokemon TCG: Japanese Basic",
        "grader": "PSA",
        "grade": "9",
        "dex_id_candidate": dex_id,
        "tcgdex_card_id_candidate": card_id,
        "tcgdex_local_id_candidate": local_id,
        "pinned_source_path": f"data-asia/PMCG/PMCG1/{local_id}.ts",
        "provider_name_dexid_exact_match": True,
        "provider_numeric_semantics_proven": False,
        "candidate_status": COHORT_STATUS,
        "macro_identity_exact": False,
        "microvariant_exact": False,
        "exact_identity_link_candidate": False,
    }


def payload(rows=None, *, cohort_set="PMCG1", set_set="PMCG1"):
    rows = rows or [
        row("A", 6, "PMCG1-021", "021"),
        row("B", 9, "PMCG1-032", "032"),
    ]
    return {
        "corroborated_groups": [
            {
                "provider_set_label": "Pokemon TCG: Japanese Basic",
                "tcgdex_set_id_candidate": set_set,
                "records_corroborated": len(rows),
                "provider_set_label_exact_for_all_rows": True,
                "provider_titles_if_present_support_registry_set": True,
                "pinned_set_source_commit": "PINNED",
                "corroboration_status": SET_STATUS,
                "macro_identity_exact": False,
                "microvariant_exact": False,
                "exact_identity_link_candidate": False,
            }
        ],
        "cohort": {
            "groups": [
                {
                    "provider_set_label": "Pokemon TCG: Japanese Basic",
                    "tcgdex_set_id_candidate": cohort_set,
                    "pinned_source_commit": "PINNED",
                    "provider_name_dexid_exact_match_for_all_rows": True,
                    "candidate_status": COHORT_STATUS,
                    "macro_identity_exact": False,
                    "exact_identity_link_candidate": False,
                    "records": rows,
                }
            ]
        },
    }


class CardovaBoundedMacroIdentityProbeTests(unittest.TestCase):
    def test_composed_chain_promotes_macro_only(self):
        result = probe.compose_registry_result(payload())
        self.assertEqual(result["macro_identity_exact_count"], 2)
        self.assertEqual(result["microvariant_exact_count"], 0)
        self.assertEqual(result["exact_identity_link_candidate_count"], 0)
        self.assertEqual(result["blocked"], {})
        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(len(result["records"]), 2)
        for item in result["records"]:
            self.assertTrue(item["macro_identity_exact"])
            self.assertTrue(item["row_bound_numeric_coordinate_verified"])
            self.assertTrue(item["set_identity_independently_corroborated"])
            self.assertTrue(item["tcgdex_card_unique_for_dex_within_set"])
            self.assertFalse(item["provider_numeric_semantics_global_claim"])
            self.assertFalse(item["microvariant_exact"])
            self.assertFalse(item["exact_identity_link_candidate"])
            self.assertFalse(item["v4_economic_use"])

    def test_set_id_conflict_fails_closed(self):
        result = probe.compose_registry_result(payload(cohort_set="PMCG1", set_set="PMCG2"))
        self.assertEqual(result["macro_identity_exact_count"], 0)
        self.assertEqual(result["blocked"], {"COHORT_SET_ID_CONFLICT": 1})

    def test_name_gate_failure_fails_closed(self):
        value = payload()
        value["cohort"]["groups"][0]["records"][0]["provider_name_dexid_exact_match"] = False
        result = probe.compose_registry_result(value)
        self.assertEqual(result["macro_identity_exact_count"], 0)
        self.assertEqual(result["blocked"], {"ROW_PROOF_CHAIN_INCOMPLETE": 1})

    def test_conflicting_card_coordinates_for_same_dex_fail_closed(self):
        rows = [
            row("A", 6, "PMCG1-021", "021"),
            row("B", 6, "PMCG1-099", "099"),
        ]
        result = probe.compose_registry_result(payload(rows))
        self.assertEqual(result["macro_identity_exact_count"], 0)
        self.assertEqual(result["blocked"], {"COHORT_DEX_CARD_NOT_UNIQUE": 1})

    def test_safety_summary_never_claims_global_number_semantics_or_writes(self):
        summary = probe.safe_summary()
        self.assertTrue(summary["row_scoped_proof_only"])
        self.assertFalse(summary["provider_numeric_semantics_global_claim"])
        for key in (
            "card_alias_table_used",
            "translation_assumed",
            "fuzzy_matching",
            "microvariant_exact",
            "canonical_link_written",
            "robot_kb_write",
            "v4_economic_use",
            "notification_sent",
            "automatic_purchase",
            "automatic_bid",
            "automatic_offer",
            "automatic_checkout",
            "automatic_payment",
        ):
            self.assertFalse(summary[key], key)


if __name__ == "__main__":
    unittest.main()
