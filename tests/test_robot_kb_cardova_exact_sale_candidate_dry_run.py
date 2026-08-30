import unittest

from mac.robot_kb_local import robot_kb_cardova_exact_sale_candidate_dry_run as dry


def identity_row(**overrides):
    row = {
        "source_native_record_id": "01TESTCARDOVA000000000000001",
        "macro_identity_exact": True,
        "microvariant_exact": True,
        "exact_identity_link_candidate": True,
        "canonical_link_written": False,
        "tcgdex_card_id": "PMCG1-011",
        "tcgdex_set_id": "PMCG1",
        "tcgdex_local_id": "011",
        "card_name_provider_claim": "Venusaur",
        "collector_number_provider_claim": "003",
        "language": "Japanese",
        "grader": "PSA",
        "grade": "9",
        "finish": "holo",
        "printing": "",
        "pinned_source_variant_dimensions": {"finish": "holo"},
    }
    row.update(overrides)
    return row


def sale_row(**overrides):
    row = {
        "source_native_record_id": "01TESTCARDOVA000000000000001",
        "card_name": "Venusaur",
        "collector_number": "3",
        "language": "Japanese",
        "grader": "PSA",
        "grade": "9",
        "certification_number": "159075586",
        "auction_end_at_utc": "2026-08-29T10:00:00+00:00",
        "final_bid_jpy": 123456,
        "currency": "JPY",
    }
    row.update(overrides)
    return row


def accepting_builder(record):
    return (object(), object()), "P3_SALE_READY_UNRESOLVED_IDENTITY"


class ExactSaleCandidateDryRunTests(unittest.TestCase):
    def test_exact_identity_and_p3_sale_contract_produce_candidate(self):
        out = dry.compose_exact_sale_candidates(
            [sale_row()], [identity_row()], sale_builder=accepting_builder
        )
        self.assertEqual(out["exact_card_sale_candidate_count"], 1)
        self.assertEqual(out["blocked"], {})
        record = out["records"][0]
        self.assertTrue(record["commercial_identity_exact"])
        self.assertTrue(record["p3_sale_contract_valid"])
        self.assertTrue(record["exact_card_sale_candidate_ready"])
        self.assertEqual(record["hammer_price_jpy"], 123456)
        self.assertEqual(record["price_component"], "HAMMER_PRICE")
        self.assertEqual(record["currency"], "JPY")
        self.assertEqual(record["certification_number"], "159075586")
        self.assertFalse(record["canonical_link_written"])
        self.assertFalse(record["robot_kb_write"])
        self.assertFalse(record["sale_transaction_written"])

    def test_microvariant_not_exact_is_blocked(self):
        out = dry.compose_exact_sale_candidates(
            [sale_row()], [identity_row(microvariant_exact=False)], sale_builder=accepting_builder
        )
        self.assertEqual(out["exact_card_sale_candidate_count"], 0)
        self.assertEqual(out["blocked"], {"MICROVARIANT_NOT_EXACT": 1})

    def test_missing_sale_source_row_is_blocked(self):
        out = dry.compose_exact_sale_candidates([], [identity_row()], sale_builder=accepting_builder)
        self.assertEqual(out["blocked"], {"SALE_SOURCE_ROW_MISSING": 1})

    def test_provider_identity_conflict_is_blocked(self):
        out = dry.compose_exact_sale_candidates(
            [sale_row(card_name="Charizard")], [identity_row()], sale_builder=accepting_builder
        )
        self.assertEqual(out["blocked"], {"SALE_IDENTITY_PROVIDER_CONFLICT": 1})

    def test_p3_sale_contract_rejection_is_preserved(self):
        def rejecting_builder(record):
            return None, "FINAL_BID_INVALID"

        out = dry.compose_exact_sale_candidates(
            [sale_row()], [identity_row()], sale_builder=rejecting_builder
        )
        self.assertEqual(out["blocked"], {"P3_SALE_CONTRACT:FINAL_BID_INVALID": 1})

    def test_duplicate_sale_source_id_is_fail_closed(self):
        out = dry.compose_exact_sale_candidates(
            [sale_row(), sale_row()], [identity_row()], sale_builder=accepting_builder
        )
        self.assertEqual(out["blocked"], {"DUPLICATE_SALE_SOURCE_ID": 1})

    def test_safety_contract(self):
        summary = dry.safe_summary()
        self.assertTrue(summary["existing_p3_sale_contract_reused"])
        self.assertFalse(summary["canonical_link_written"])
        self.assertFalse(summary["robot_kb_write"])
        self.assertFalse(summary["sale_transaction_written"])
        self.assertFalse(summary["v4_economic_use"])
        self.assertFalse(summary["automatic_purchase"])
        self.assertFalse(summary["automatic_bid"])
        self.assertFalse(summary["automatic_checkout"])
        self.assertFalse(summary["automatic_payment"])


if __name__ == "__main__":
    unittest.main()
