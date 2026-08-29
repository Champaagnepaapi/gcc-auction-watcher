from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "mac" / "robot-kb-local" / "robot_kb_cardova_past_auction_probe.py"
SPEC = importlib.util.spec_from_file_location("robot_kb_cardova_past_auction_probe", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class CardovaPastAuctionProbeTests(unittest.TestCase):
    def test_public_cardova_https_only(self):
        self.assertTrue(mod._allowed_url("https://www.cardova.co.jp/en/auction/close?kind=1&page=1"))
        self.assertTrue(mod._allowed_url("https://api.cardova.co.jp/example"))
        self.assertFalse(mod._allowed_url("http://www.cardova.co.jp/en/auction/close"))
        self.assertFalse(mod._allowed_url("https://evil.example/auction/close"))

    def test_requires_final_price_end_and_card_shape(self):
        row = {
            "ulid": "01ABC",
            "bid_price": 57776,
            "end_date": "2025-09-21T12:20:00+09:00",
            "card_number": "174",
        }
        self.assertTrue(mod._looks_like_past_auction_row(row))
        self.assertFalse(mod._looks_like_past_auction_row({**row, "bid_price": None}))
        self.assertFalse(mod._looks_like_past_auction_row({**row, "end_date": None}))
        self.assertFalse(mod._looks_like_past_auction_row({**row, "card_number": None}))

    def test_projection_keeps_public_status_but_drops_sensitive_keys(self):
        row = {
            "ulid": "01ABC",
            "bid_price": 57776,
            "end_date": "2025-09-21",
            "card_number": "174",
            "payment_status": "closed",
            "transaction_status": "completed",
            "member_id": "secret-member",
            "account_email": "x@example.com",
        }
        projected = mod._project_row(row)
        self.assertEqual(projected["payment_status"], "closed")
        self.assertEqual(projected["transaction_status"], "completed")
        self.assertNotIn("member_id", projected)
        self.assertNotIn("account_email", projected)

    def test_safety_flags_never_promote_public_row_to_sale(self):
        summary = mod.safe_summary()
        self.assertFalse(summary["public_past_auction_rows_promoted_to_sale"])
        self.assertFalse(summary["payment_semantics_proven"])
        self.assertFalse(summary["sale_transaction_ready"])
        self.assertFalse(summary["robot_kb_write"])
        self.assertFalse(summary["sale_transaction_stored"])
        self.assertFalse(summary["v4_economic_use"])
        self.assertFalse(summary["automatic_purchase"])
        self.assertFalse(summary["automatic_bid"])
        self.assertFalse(summary["automatic_offer"])
        self.assertFalse(summary["automatic_checkout"])
        self.assertFalse(summary["automatic_payment"])


if __name__ == "__main__":
    unittest.main()
