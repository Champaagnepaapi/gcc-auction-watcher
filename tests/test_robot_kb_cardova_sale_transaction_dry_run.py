from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


P3_AVAILABLE = importlib.util.find_spec("robot_kb") is not None
PATH = Path("mac/robot-kb-local/robot_kb_cardova_sale_transaction_dry_run.py")
EXACT_PATH = Path("mac/robot-kb-local/robot_kb_cardova_exact_sale_candidate_dry_run.py")

if P3_AVAILABLE:
    from robot_kb.domain import ObservationType

    SPEC = importlib.util.spec_from_file_location("cardova_sale_transaction_dry_run", PATH)
    MOD = importlib.util.module_from_spec(SPEC)
    assert SPEC.loader is not None
    SPEC.loader.exec_module(MOD)

    EXACT_SPEC = importlib.util.spec_from_file_location("cardova_exact_sale_candidate_dry_run", EXACT_PATH)
    EXACT = importlib.util.module_from_spec(EXACT_SPEC)
    assert EXACT_SPEC.loader is not None
    EXACT_SPEC.loader.exec_module(EXACT)
else:
    ObservationType = None
    MOD = None
    EXACT = None


def paid_record() -> dict:
    return {
        "source": "cardova_public_past_auction",
        "source_native_record_id": "01TESTCARDOVAPAIDSALE",
        "source_url": "https://www.cardova.co.jp/en/auction/card/01TESTCARDOVAPAIDSALE",
        "provider_sale_status": "PAID_COMPLETED",
        "provider_sale_status_proven": True,
        "bid_payment_status": 5,
        "finished": 1,
        "canceled_at": None,
        "re_listed": 0,
        "re_listing_count": 0,
        "final_bid_jpy": 123456,
        "currency": "JPY",
        "currency_proven": True,
        "price_component": "PROVIDER_FINAL_WINNING_BID",
        "all_in_price_proven": False,
        "auction_end_at_raw": "2026-08-29T21:00:00+09:00",
        "auction_end_at_utc": "2026-08-29T12:00:00+00:00",
        "payment_completed_at": "",
        "payment_completed_at_proven": False,
        "grader": "PSA",
        "grade": "10",
        "certification_number": "123456789",
        "language": "Japanese",
        "card_name": "Pikachu",
        "set_name": "Pokemon TCG: Japanese XY Promo",
        "collector_number": "#279/XY-P",
        "provider_set_name_short": "20th Anniversary Festa",
        "provider_series": "Pokemon TCG: Japanese XY Promo",
        "provider_title": "Pikachu 279/XY-P PSA 10",
        "provider_item_name": "Pikachu",
        "provider_card_ulid": "CARD01",
        "sale_evidence_ready": True,
        "sale_transaction_ready": False,
    }


def exact_identity_row() -> dict:
    return {
        "source_native_record_id": "01TESTCARDOVAPAIDSALE",
        "macro_identity_exact": True,
        "microvariant_exact": True,
        "exact_identity_link_candidate": True,
        "canonical_link_written": False,
        "tcgdex_card_id": "PROMO-XY-279",
        "tcgdex_set_id": "PROMO-XY",
        "tcgdex_local_id": "279",
        "card_name_provider_claim": "Pikachu",
        "collector_number_provider_claim": "#279/XY-P",
        "language": "Japanese",
        "grader": "PSA",
        "grade": "10",
        "finish": "normal",
        "printing": "",
        "pinned_source_variant_dimensions": {"finish": "non_holo"},
    }


@unittest.skipUnless(
    P3_AVAILABLE,
    "pinned Robot KB P3 runtime is not present in this V4-only test lane",
)
class CardovaSaleTransactionDryRunTests(unittest.TestCase):
    def test_valid_paid_row_builds_unresolved_p3_sale(self):
        built, reason = MOD.build_p3_sale(
            paid_record(), observed_at="2026-08-30T08:00:00+00:00"
        )
        self.assertEqual(reason, "P3_SALE_READY_UNRESOLVED_IDENTITY")
        self.assertIsNotNone(built)
        assert built is not None
        raw, observation = built
        self.assertEqual(raw.source_code, "cardova")
        self.assertEqual(observation.observation_type, ObservationType.SALE_TRANSACTION)
        self.assertEqual(observation.event_at, "2026-08-29T12:00:00+00:00")
        self.assertEqual(
            observation.fact["sale_occurred_at"], "2026-08-29T12:00:00+00:00"
        )
        self.assertEqual(observation.fact["transaction_status"], "COMPLETED")
        self.assertTrue(observation.genuine_sale_evidence)
        self.assertFalse(observation.exact_identity_eligible)
        self.assertEqual(
            set(observation.unresolved_dimensions),
            {"canonical_identity", "commercial_microvariant"},
        )
        self.assertEqual(len(observation.prices), 1)
        price = observation.prices[0]
        self.assertEqual(price.component_type, "HAMMER_PRICE")
        self.assertEqual(price.amount_minor, 123456)
        self.assertEqual(price.currency, "JPY")

    def test_payment_completion_timestamp_is_not_fabricated(self):
        built, _reason = MOD.build_p3_sale(
            paid_record(), observed_at="2026-08-30T08:00:00+00:00"
        )
        assert built is not None
        _raw, observation = built
        self.assertNotIn("payment_completed_at", observation.fact)
        summary = MOD.safe_summary()
        self.assertFalse(summary["payment_completion_timestamp_fabricated"])
        self.assertEqual(summary["sale_event_semantics"], "AUCTION_END_AT_UTC")

    def test_unproven_paid_state_currency_bad_bid_and_future_event_block(self):
        cases = []

        row = paid_record()
        row["provider_sale_status"] = "PAYMENT_PENDING"
        cases.append((row, "PAID_COMPLETED_STATUS_MISSING"))

        row = paid_record()
        row["currency_proven"] = False
        cases.append((row, "CURRENCY_UNPROVEN"))

        row = paid_record()
        row["final_bid_jpy"] = 0
        cases.append((row, "FINAL_BID_INVALID"))

        for row, expected in cases:
            built, reason = MOD.build_p3_sale(
                row, observed_at="2026-08-30T08:00:00+00:00"
            )
            self.assertIsNone(built)
            self.assertEqual(reason, expected)

        built, reason = MOD.build_p3_sale(
            paid_record(), observed_at="2026-08-29T11:59:59+00:00"
        )
        self.assertIsNone(built)
        self.assertEqual(reason, "SALE_EVENT_AFTER_OBSERVATION")

    def test_memory_dry_run_persists_unresolved_sale_and_replays_idempotently(self):
        summary = MOD.run_memory_dry_run(
            [paid_record()],
            max_records=1,
            observed_at="2026-08-30T08:00:00+00:00",
            replay=True,
        )
        self.assertEqual(summary["prepared_sale_transactions"], 1)
        self.assertEqual(summary["blocked"], {})
        self.assertEqual(summary["sale_transactions_stored_in_memory"], 1)
        self.assertEqual(summary["unresolved_identity_sales"], 1)
        self.assertEqual(summary["canonical_card_links"], 0)
        self.assertEqual(summary["hammer_price_jpy_rows"], 1)
        self.assertEqual(summary["sale_transactions_after_replay"], 1)
        self.assertEqual(summary["duplicate_sale_replays"], 1)
        self.assertEqual(summary["first_pass_diagnostics"]["sale_transactions_stored"], 1)
        self.assertEqual(summary["replay_diagnostics"]["sale_transactions_stored"], 0)

    def test_identical_input_rows_are_not_silently_two_sales(self):
        row = paid_record()
        summary = MOD.run_memory_dry_run(
            [row, dict(row)],
            max_records=2,
            observed_at="2026-08-30T08:00:00+00:00",
            replay=False,
        )
        self.assertEqual(summary["prepared_sale_transactions"], 2)
        self.assertEqual(summary["sale_transactions_stored_in_memory"], 1)
        self.assertEqual(summary["canonical_card_links"], 0)
        self.assertEqual(summary["hammer_price_jpy_rows"], 1)

    def test_exact_identity_candidate_reuses_same_p3_sale_contract(self):
        summary = EXACT.compose_exact_sale_candidates(
            [paid_record()],
            [exact_identity_row()],
            observed_at="2026-08-30T08:00:00+00:00",
        )
        self.assertEqual(summary["exact_card_sale_candidate_count"], 1)
        self.assertEqual(summary["blocked"], {})
        record = summary["records"][0]
        self.assertTrue(record["p3_sale_contract_valid"])
        self.assertTrue(record["commercial_identity_exact"])
        self.assertTrue(record["exact_card_sale_candidate_ready"])
        self.assertEqual(record["sale_occurred_at"], "2026-08-29T12:00:00+00:00")
        self.assertEqual(record["hammer_price_jpy"], 123456)
        self.assertEqual(record["price_component"], "HAMMER_PRICE")
        self.assertEqual(record["currency"], "JPY")
        self.assertFalse(record["canonical_link_written"])
        self.assertFalse(record["robot_kb_write"])
        self.assertFalse(record["sale_transaction_written"])
        self.assertFalse(record["v4_economic_use"])

        blocked_identity = exact_identity_row()
        blocked_identity["microvariant_exact"] = False
        blocked = EXACT.compose_exact_sale_candidates(
            [paid_record()],
            [blocked_identity],
            observed_at="2026-08-30T08:00:00+00:00",
        )
        self.assertEqual(blocked["exact_card_sale_candidate_count"], 0)
        self.assertEqual(blocked["blocked"], {"MICROVARIANT_NOT_EXACT": 1})

    def test_safety_contract_has_no_durable_write_or_commerce(self):
        summary = MOD.safe_summary()
        self.assertEqual(summary["database"], ":memory:")
        self.assertFalse(summary["durable_robot_kb_write"])
        self.assertFalse(summary["canonical_identity_claimed"])
        self.assertFalse(summary["commercial_microvariant_claimed"])
        self.assertFalse(summary["exact_identity_eligible"])
        for key in (
            "v4_economic_use",
            "notification_sent",
            "automatic_purchase",
            "automatic_bid",
            "automatic_offer",
            "automatic_checkout",
            "automatic_payment",
        ):
            self.assertFalse(summary[key], key)

        exact_summary = EXACT.safe_summary()
        self.assertTrue(exact_summary["existing_p3_sale_contract_reused"])
        self.assertFalse(exact_summary["canonical_link_written"])
        self.assertFalse(exact_summary["robot_kb_write"])
        self.assertFalse(exact_summary["sale_transaction_written"])
        self.assertFalse(exact_summary["v4_economic_use"])
        self.assertFalse(exact_summary["automatic_purchase"])
        self.assertFalse(exact_summary["automatic_bid"])
        self.assertFalse(exact_summary["automatic_checkout"])
        self.assertFalse(exact_summary["automatic_payment"])


if __name__ == "__main__":
    unittest.main()
