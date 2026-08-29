from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "mac" / "robot-kb-local" / "robot_kb_fanatics_paid_pending_capture.py"
SPEC = importlib.util.spec_from_file_location("robot_kb_fanatics_paid_pending_capture", MODULE_PATH)
assert SPEC and SPEC.loader
capture = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = capture
SPEC.loader.exec_module(capture)


def live_shape(**overrides):
    row = {
        "auctionType": "PREMIER",
        "category": "Pokémon",
        "grade": 10.0,
        "gradingService": "PSA",
        "id": "PREMIER17603",
        "isComplete": True,
        "listingUuid": "995c1bb4-fe03-11f0-92aa-0af9eda8a431",
        "paymentStatus": "Paid",
        "purchasePrice": "528000.00",
        "serial": "05302786",
        "soldDate": "2026-02-19T22:01:40.000 PST",
        "title": "1999 Pokemon English Base Set Shadowless 1st Edition Holo Charizard #4 PSA 10 GEM MINT",
        "year": 1999,
    }
    row.update(overrides)
    return row


class PendingCaptureTests(unittest.TestCase):
    def test_paid_sale_is_retained_pending_without_identity_or_currency_claim(self):
        row, reason = capture.base.precheck_row(live_shape())
        self.assertEqual(reason, "PAID_COMPLETE_INDIVIDUAL_CARD")
        assert row is not None
        record = capture.pending_record(row)
        self.assertTrue(record["paid_sale_status_proven"])
        self.assertTrue(record["provider_purchase_price_proven"])
        self.assertEqual(record["identity_status"], "PENDING_TCGDEX")
        self.assertEqual(record["microvariant_status"], "PENDING_TCGDEX")
        self.assertFalse(record["currency_proven"])
        self.assertFalse(record["robot_kb_sale_ready"])

    def test_capture_keeps_paid_rows_and_blocks_unpaid_without_tcgdex(self):
        rows = [
            live_shape(),
            live_shape(id="PREMIER17604", paymentStatus="Unpaid"),
        ]

        def fetcher(**_kwargs):
            return {
                "_embedded": {"SalesRecords": rows},
                "page": {"totalPages": 1},
            }

        report = capture.run_capture(
            queries=("Pokemon English PSA 10",),
            pages_per_query=1,
            page_size=20,
            timeout_seconds=5,
            fetcher=fetcher,
        )
        self.assertEqual(report["rows_seen"], 2)
        self.assertEqual(report["pending_identity_count"], 1)
        self.assertEqual(report["blocked"], {"PAYMENT_NOT_PAID": 1})
        self.assertEqual(report["tcgdex_requests"], 0)
        self.assertFalse(report["identity_resolution_attempted"])
        self.assertFalse(report["robot_kb_write"])
        self.assertFalse(report["sale_transaction_stored"])

    def test_capture_script_has_no_database_or_secret_dependency(self):
        text = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("ROBOT_KB_DATABASE_URL", text)
        self.assertNotIn("find-generic-password", text)
        self.assertNotIn("KnowledgeBase(", text)


if __name__ == "__main__":
    unittest.main()
