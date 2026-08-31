from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


P3_AVAILABLE = importlib.util.find_spec("robot_kb") is not None
PATH = Path("mac/robot-kb-local/robot_kb_cardova_canonical_sale_persistence_dry_run.py")

if P3_AVAILABLE:
    SPEC = importlib.util.spec_from_file_location("cardova_canonical_sale_memory_dry_run", PATH)
    MOD = importlib.util.module_from_spec(SPEC)
    assert SPEC.loader is not None
    SPEC.loader.exec_module(MOD)
else:
    MOD = None


def sale_row(source_id: str = "01TESTCARDOVACANONICAL0000001", **overrides):
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
        "set_name": "Pokemon TCG: Japanese Jungle",
        "collector_number": "1",
        "sale_evidence_ready": True,
        "sale_transaction_ready": False,
    }
    row.update(overrides)
    return row


def identity_row(source_id: str = "01TESTCARDOVACANONICAL0000001", **overrides):
    row = {
        "source_native_record_id": source_id,
        "card_name_provider_claim": "Testmon",
        "collector_number_provider_claim": "1",
        "provider_set_label": "Pokemon TCG: Japanese Jungle",
        "grader": "PSA",
        "grade": "9",
        "language": "Japanese",
        "tcgdex_card_id": "PMCG2-001",
        "tcgdex_set_id": "PMCG2",
        "tcgdex_local_id": "001",
        "finish_exact": True,
        "finish": "holo",
        "pinned_source_variant_exact": True,
        "pinned_source_variant_dimensions": {"finish": "holo"},
        "pinned_source_variant_opaque": [],
        "printing_exact": False,
        "printing": "",
        "printing_applicability_exact": True,
        "printing_applicability_reason": "NOT_APPLICABLE_IN_PINNED_SOURCE_VARIANT",
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
class CardovaCanonicalSalePersistenceDryRunTests(unittest.TestCase):
    def test_simple_exact_japanese_variant_maps_to_existing_p3_registry(self):
        plan, reason = MOD.canonical_plan(identity_row(), sale_row())
        self.assertEqual(reason, "P3_CANONICAL_PLAN_READY")
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.canonical_set_key, "tcgdex:ja:PMCG2")
        self.assertEqual(plan.tcgdex_local_id, "001")
        self.assertEqual(plan.profile_assignments, {"finish": "HOLO"})
        self.assertEqual(
            plan.applicability,
            {
                "edition_stamp": "NOT_APPLICABLE",
                "finish": "APPLICABLE",
                "foil_pattern": "NOT_APPLICABLE",
            },
        )

    def test_no_rarity_printing_is_not_collapsed_into_finish_only(self):
        row = identity_row(
            printing_exact=True,
            printing="no_rarity_symbol",
            printing_applicability_reason="PINNED_SOURCE_VARIANT_EXPLICIT",
            pinned_source_variant_dimensions={
                "finish": "holo",
                "printing": "no_rarity_symbol",
            },
        )
        plan, reason = MOD.canonical_plan(row, sale_row())
        self.assertIsNone(plan)
        self.assertEqual(reason, "P3_SCHEMA_PRINTING_AXIS_UNREPRESENTABLE")

    def test_visible_symbol_ordinary_variant_is_also_blocked_until_p3_has_printing_axis(self):
        row = identity_row(
            printing_applicability_reason=(
                "NO_RARITY_EXCLUDED_BY_REVIEWED_VISIBLE_RARITY_SYMBOL"
            )
        )
        plan, reason = MOD.canonical_plan(row, sale_row())
        self.assertIsNone(plan)
        self.assertEqual(reason, "P3_SCHEMA_PRINTING_AXIS_UNREPRESENTABLE")

    def test_one_exact_candidate_creates_canonical_link_and_exact_sale_only_in_memory(self):
        result = MOD.run_memory_dry_run(
            [sale_row()],
            [identity_row()],
            observed_at="2026-08-30T08:00:00+00:00",
            replay=True,
        )
        self.assertEqual(result["exact_sale_candidates_from_205"], 1)
        self.assertEqual(result["exact_sale_candidate_blocked_from_205"], {})
        self.assertEqual(result["p3_schema_representable_count"], 1)
        self.assertEqual(result["p3_schema_blocked_count"], 0)
        self.assertEqual(result["canonical_cards_created_in_memory"], 1)
        self.assertEqual(result["proven_cardova_identifier_links_in_memory"], 1)
        self.assertEqual(result["exact_sale_transactions_in_memory"], 1)
        self.assertEqual(result["exact_sale_rows_verified"], 1)
        self.assertEqual(result["hammer_price_jpy_rows_verified"], 1)
        self.assertEqual(result["exact_identity_links_reported"], 1)
        self.assertEqual(result["sale_transactions_stored_reported"], 1)
        self.assertEqual(result["duplicate_sale_replays"], 1)
        self.assertEqual(result["blocked"], {})
        self.assertFalse(result["durable_robot_kb_write"])
        self.assertFalse(result["local_postgres_write"])

    def test_two_sales_for_same_exact_print_reuse_one_canonical_card(self):
        source2 = "01TESTCARDOVACANONICAL0000002"
        result = MOD.run_memory_dry_run(
            [
                sale_row(),
                sale_row(
                    source2,
                    certification_number="159075587",
                    final_bid_jpy=130000,
                ),
            ],
            [identity_row(), identity_row(source2)],
            observed_at="2026-08-30T08:00:00+00:00",
            replay=True,
        )
        self.assertEqual(result["exact_sale_candidates_from_205"], 2)
        self.assertEqual(result["p3_schema_representable_count"], 2)
        self.assertEqual(result["canonical_cards_created_in_memory"], 1)
        self.assertEqual(result["proven_cardova_identifier_links_in_memory"], 2)
        self.assertEqual(result["exact_sale_transactions_in_memory"], 2)
        self.assertEqual(result["duplicate_sale_replays"], 2)
        self.assertEqual(result["blocked"], {})

    def test_schema_gap_is_reported_without_blocking_representable_rows(self):
        source2 = "01TESTCARDOVACANONICAL0000002"
        no_rarity = identity_row(
            source2,
            printing_exact=True,
            printing="no_rarity_symbol",
            printing_applicability_reason="PINNED_SOURCE_VARIANT_EXPLICIT",
            pinned_source_variant_dimensions={
                "finish": "holo",
                "printing": "no_rarity_symbol",
            },
        )
        result = MOD.run_memory_dry_run(
            [sale_row(), sale_row(source2, certification_number="159075587")],
            [identity_row(), no_rarity],
            observed_at="2026-08-30T08:00:00+00:00",
            replay=False,
        )
        self.assertEqual(result["exact_sale_candidates_from_205"], 2)
        self.assertEqual(result["p3_schema_representable_count"], 1)
        self.assertEqual(result["p3_schema_blocked_count"], 1)
        self.assertEqual(
            result["blocked"],
            {"P3_SCHEMA_PRINTING_AXIS_UNREPRESENTABLE": 1},
        )
        self.assertEqual(result["exact_sale_transactions_in_memory"], 1)

    def test_safety_contract(self):
        summary = MOD.safe_summary()
        self.assertTrue(summary["predecessor_194_canonical_pattern_reused"])
        self.assertTrue(summary["predecessor_195_batch_pattern_reused"])
        self.assertTrue(summary["cardova_205_exact_sale_gate_reused"])
        self.assertTrue(summary["p3_sale_builder_reused"])
        self.assertFalse(summary["tcgdex_bare_card_id_link_created"])
        self.assertTrue(summary["printing_schema_gap_fail_closed"])
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
