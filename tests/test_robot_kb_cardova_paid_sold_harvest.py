import importlib.util
from pathlib import Path
import unittest


PATH = Path("mac/robot-kb-local/robot_kb_cardova_paid_sold_harvest.py")
SPEC = importlib.util.spec_from_file_location("cardova_paid_sold_harvest", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


def base_row():
    return {
        "ulid": "01ABC",
        "listing_type": 1,
        "bid_price": 123456,
        "finished": 1,
        "end_date": "2026-08-01T21:00:00+09:00",
        "bid_payment_status": 5,
        "seller_payment_status": None,
        "canceled_at": None,
        "re_listed": 0,
        "re_listing_count": 0,
        "authentication_company_code": "P",
        "grade": "10.0",
        "language": "Japanese",
        "player": "Pikachu",
        "variety": "Pokemon TCG: Japanese Promo",
        "variety_short": "Promo",
        "card_number": "#001/SV-P",
        "certificate_number": "123456789",
    }


class CardovaPaidSoldHarvestTests(unittest.TestCase):
    def test_exact_reviewed_paid_state_is_sale_evidence_ready(self):
        record, reason = MOD.classify_paid_sold_row(base_row())
        self.assertEqual(reason, "PAID_SOLD_EVIDENCE_READY")
        self.assertIsNotNone(record)
        assert record is not None
        self.assertTrue(record["provider_sale_status_proven"])
        self.assertEqual(record["provider_sale_status"], "PAID_COMPLETED")
        self.assertEqual(record["bid_payment_status"], 5)
        self.assertEqual(record["currency"], "JPY")
        self.assertTrue(record["currency_proven"])
        self.assertTrue(record["sale_evidence_ready"])
        self.assertFalse(record["payment_completed_at_proven"])
        self.assertEqual(record["identity_status"], "PENDING_TCGDEX")
        self.assertFalse(record["sale_transaction_ready"])

    def test_pending_status_is_never_sale_evidence(self):
        for status in (1, 2, 3, 4):
            row = base_row()
            row["bid_payment_status"] = status
            record, reason = MOD.classify_paid_sold_row(row)
            self.assertIsNone(record)
            self.assertEqual(reason, "PAYMENT_PENDING")

    def test_unknown_payment_status_is_fail_closed(self):
        row = base_row()
        row["bid_payment_status"] = 6
        record, reason = MOD.classify_paid_sold_row(row)
        self.assertIsNone(record)
        self.assertEqual(reason, "BID_PAYMENT_STATUS_UNPROVEN")

    def test_canceled_or_relisted_is_blocked(self):
        cases = (
            ("canceled_at", "2026-08-02T00:00:00+09:00", "CANCELED"),
            ("re_listed", 1, "RELISTED"),
            ("re_listing_count", 1, "RELISTED"),
        )
        for field, value, expected in cases:
            row = base_row()
            row[field] = value
            record, reason = MOD.classify_paid_sold_row(row)
            self.assertIsNone(record)
            self.assertEqual(reason, expected)

    def test_production_scope_is_reused_and_blocks_unsupported_identity(self):
        row = base_row()
        row["language"] = "Simplified Chinese"
        record, reason = MOD.classify_paid_sold_row(row)
        self.assertIsNone(record)
        self.assertEqual(reason, "SCOPE_UNSUPPORTED_LANGUAGE")

        row = base_row()
        row["grade"] = "7"
        record, reason = MOD.classify_paid_sold_row(row)
        self.assertIsNone(record)
        self.assertEqual(reason, "SCOPE_UNSUPPORTED_GRADE")

        row = base_row()
        row["card_number"] = ""
        record, reason = MOD.classify_paid_sold_row(row)
        self.assertIsNone(record)
        self.assertEqual(reason, "SCOPE_MISSING_CARD_NUMBER")

    def test_bad_cert_or_end_time_blocks(self):
        row = base_row()
        row["certificate_number"] = ""
        record, reason = MOD.classify_paid_sold_row(row)
        self.assertIsNone(record)
        self.assertEqual(reason, "CERT_NUMBER_UNPROVEN")

        row = base_row()
        row["end_date"] = "not-a-time"
        record, reason = MOD.classify_paid_sold_row(row)
        self.assertIsNone(record)
        self.assertEqual(reason, "AUCTION_END_INVALID")

    def test_summary_counts_ready_and_blocked_rows(self):
        ready = base_row()
        pending = base_row()
        pending["ulid"] = "01DEF"
        pending["bid_payment_status"] = 4
        summary = MOD.summarize_rows([ready, pending])
        self.assertEqual(summary["rows_seen"], 2)
        self.assertEqual(summary["paid_sold_evidence_count"], 1)
        self.assertEqual(summary["blocked"], {"PAYMENT_PENDING": 1})
        self.assertEqual(len(summary["records"]), 1)

    def test_safety_contract_has_no_write_or_transaction(self):
        summary = MOD.safe_summary()
        self.assertTrue(summary["payment_semantics_proven"])
        self.assertEqual(summary["paid_bid_status_required"], 5)
        self.assertEqual(summary["payment_pending_max_status"], 4)
        self.assertTrue(summary["currency_semantics_proven"])
        self.assertEqual(summary["proven_currency"], "JPY")
        self.assertFalse(summary["identity_resolution_attempted"])
        self.assertEqual(summary["tcgdex_requests"], 0)
        self.assertFalse(summary["sale_transaction_ready"])
        for key in (
            "credentials_used",
            "cookies_supplied",
            "storage_state_supplied",
            "authentication_headers_supplied",
            "request_headers_captured",
            "posts_issued",
            "direct_api_replay_used",
            "robot_kb_write",
            "sale_transaction_stored",
            "v4_economic_use",
            "automatic_purchase",
            "automatic_bid",
            "automatic_offer",
            "automatic_checkout",
            "automatic_payment",
        ):
            self.assertFalse(summary[key], key)


if __name__ == "__main__":
    unittest.main()
