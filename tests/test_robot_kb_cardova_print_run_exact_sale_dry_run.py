from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


P3_AVAILABLE = importlib.util.find_spec("robot_kb") is not None
PATH = Path("mac/robot-kb-local/robot_kb_cardova_print_run_exact_sale_dry_run.py")

if P3_AVAILABLE:
    SPEC = importlib.util.spec_from_file_location("cardova_print_run_exact_sale_dry_run", PATH)
    MOD = importlib.util.module_from_spec(SPEC)
    assert SPEC.loader is not None
    sys.modules[SPEC.name] = MOD
    SPEC.loader.exec_module(MOD)
else:
    MOD = None


def sale_row(source_id: str = "01TESTCARDOVAPRINTRUN0000001", **overrides):
    row = {
        "source": "cardova_public_past_auction",
        "source_native_record_id": source_id,
        "source_url": f"https://www.cardova.co.jp/en/auction/card/{source_id}",
        "provider_sale_status": "PAID_COMPLETED",
        "provider_sale_status_proven": True,
        "final_bid_jpy": 123456,
        "currency": "JPY",
        "currency_proven": True,
        "auction_end_at_utc": "2026-08-29T12:00:00+00:00",
        "certification_number": "159075586",
        "grader": "PSA",
        "grade": "9",
        "language": "Japanese",
        "card_name": "Testmon",
        "set_name": "Pokemon TCG: Japanese Basic",
        "collector_number": "1",
        "sale_evidence_ready": True,
        "sale_transaction_ready": False,
    }
    row.update(overrides)
    return row


def identity_row(source_id: str = "01TESTCARDOVAPRINTRUN0000001", **overrides):
    row = {
        "source_native_record_id": source_id,
        "card_name_provider_claim": "Testmon",
        "collector_number_provider_claim": "1",
        "provider_set_label": "Pokemon TCG: Japanese Basic",
        "grader": "PSA",
        "grade": "9",
        "language": "Japanese",
        "tcgdex_card_id": "PMCG1-001",
        "tcgdex_set_id": "PMCG1",
        "tcgdex_local_id": "001",
        "finish_exact": True,
        "finish": "holo",
        "pinned_source_variant_exact": True,
        "pinned_source_variant_dimensions": {"finish": "holo"},
        "pinned_source_variant_opaque": [],
        "printing_exact": False,
        "printing": "",
        "printing_applicability_exact": True,
        "printing_applicability_reason": "NO_RARITY_EXCLUDED_BY_REVIEWED_VISIBLE_RARITY_SYMBOL",
        "edition_exact": False,
        "edition": "",
        "edition_applicability_exact": True,
        "edition_applicability_reason": "NOT_APPLICABLE_IN_PINNED_SOURCE_VARIANT",
        "special_finish_exact": False,
        "special_finish": "",
        "special_finish_applicability_exact": True,
        "special_finish_applicability_reason": "NOT_APPLICABLE_IN_PINNED_SOURCE_VARIANT",
        "remaining_unproven_axes": [],
        "macro_identity_exact": True,
        "microvariant_exact": True,
        "exact_identity_link_candidate": True,
        "canonical_link_written": False,
    }
    row.update(overrides)
    return row


@unittest.skipUnless(P3_AVAILABLE, "pinned Robot KB P3 runtime is required")
class CardovaPrintRunExactSaleDryRunTests(unittest.TestCase):
    def test_explicit_no_rarity_maps_to_print_run_without_edition_inference(self):
        identity = identity_row(
            printing_exact=True,
            printing="no_rarity_symbol",
            printing_applicability_reason="PINNED_SOURCE_VARIANT_EXPLICIT",
            pinned_source_variant_dimensions={
                "finish": "holo",
                "printing": "no_rarity_symbol",
            },
        )
        plan, reason = MOD.canonical_plan(identity, sale_row())
        self.assertEqual(reason, "P3_CANONICAL_PLAN_READY")
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.profile_assignments["print_run"], "NO_RARITY_SYMBOL")
        self.assertNotIn("edition_stamp", plan.profile_assignments)
        self.assertEqual(plan.applicability["print_run"], "APPLICABLE")

    def test_reviewed_visible_symbol_maps_to_rarity_symbol_present(self):
        plan, reason = MOD.canonical_plan(identity_row(), sale_row())
        self.assertEqual(reason, "P3_CANONICAL_PLAN_READY")
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.profile_assignments["print_run"], "RARITY_SYMBOL_PRESENT")
        self.assertNotIn("edition_stamp", plan.profile_assignments)

    def test_unknown_explicit_printing_stays_fail_closed(self):
        identity = identity_row(
            printing_exact=True,
            printing="mystery_print",
            printing_applicability_reason="PINNED_SOURCE_VARIANT_EXPLICIT",
            pinned_source_variant_dimensions={
                "finish": "holo",
                "printing": "mystery_print",
            },
        )
        plan, reason = MOD.canonical_plan(identity, sale_row())
        self.assertIsNone(plan)
        self.assertEqual(reason, "P3_PRINT_RUN_MAPPING_UNSUPPORTED")

    def test_no_rarity_and_symbol_present_are_distinct_exact_cards_and_sales(self):
        source2 = "01TESTCARDOVAPRINTRUN0000002"
        no_rarity = identity_row(
            printing_exact=True,
            printing="no_rarity_symbol",
            printing_applicability_reason="PINNED_SOURCE_VARIANT_EXPLICIT",
            pinned_source_variant_dimensions={
                "finish": "holo",
                "printing": "no_rarity_symbol",
            },
        )
        symbol_present = identity_row(source2)
        result = MOD.run_memory_dry_run(
            [
                sale_row(),
                sale_row(source2, certification_number="159075587", final_bid_jpy=130000),
            ],
            [no_rarity, symbol_present],
            observed_at="2026-08-31T12:00:00+00:00",
            replay=True,
        )
        self.assertEqual(result["exact_sale_candidates_from_205"], 2)
        self.assertEqual(result["p3_schema_representable_count"], 2)
        self.assertEqual(result["p3_schema_blocked_count"], 0)
        self.assertEqual(result["blocked"], {})
        self.assertEqual(result["canonical_cards_created_in_memory"], 2)
        self.assertEqual(result["proven_cardova_identifier_links_in_memory"], 2)
        self.assertEqual(result["exact_sale_transactions_in_memory"], 2)
        self.assertEqual(result["hammer_price_jpy_rows_verified"], 2)
        self.assertEqual(result["duplicate_sale_replays"], 2)

    def test_run_restores_206_canonical_plan_after_memory_dry_run(self):
        before = MOD.base.canonical_plan
        result = MOD.run_memory_dry_run(
            [sale_row()],
            [identity_row()],
            observed_at="2026-08-31T12:00:00+00:00",
            replay=False,
        )
        self.assertEqual(result["p3_schema_representable_count"], 1)
        self.assertIs(MOD.base.canonical_plan, before)

    def test_safety_contract(self):
        summary = MOD.safe_summary()
        self.assertTrue(summary["p3_207_print_run_registry_reused"])
        self.assertTrue(summary["proof_preserving_print_run_mapping"])
        self.assertTrue(summary["unsupported_printing_fail_closed"])
        self.assertFalse(summary["no_rarity_implies_first_edition"])
        self.assertFalse(summary["rarity_symbol_present_implies_unlimited"])
        self.assertEqual(summary["database"], ":memory:")
        for key in (
            "durable_robot_kb_write",
            "local_postgres_write",
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
