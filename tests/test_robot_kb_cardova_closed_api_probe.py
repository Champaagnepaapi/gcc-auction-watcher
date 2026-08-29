import importlib.util
from pathlib import Path
import unittest


PATH = Path("mac/robot-kb-local/robot_kb_cardova_closed_api_probe.py")
SPEC = importlib.util.spec_from_file_location("cardova_closed_probe", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


class CardovaClosedApiProbeTests(unittest.TestCase):
    def test_only_public_bg_cardova_https_is_allowed(self):
        self.assertTrue(MOD._allowed_url(MOD.DEFAULT_URL))
        self.assertFalse(MOD._allowed_url("http://bg.cardova.co.jp/api/v1/auction/list"))
        self.assertFalse(MOD._allowed_url("https://evil.example/api/v1/auction/list"))

    def test_closed_row_requires_ulid_price_end_and_identity(self):
        row = {
            "ulid": "01ABC",
            "bid_price": 12345,
            "end_date": "2026-08-01T00:00:00Z",
            "player": "Pikachu",
        }
        self.assertTrue(MOD._looks_like_closed_row(row))
        for missing in ("ulid", "bid_price", "end_date", "player"):
            candidate = dict(row)
            candidate.pop(missing)
            if missing == "end_date":
                candidate.pop("scheduled_end_date", None)
            self.assertFalse(MOD._looks_like_closed_row(candidate), missing)

    def test_projection_keeps_market_fields_but_not_account_fields(self):
        row = {
            "ulid": "01ABC",
            "bid_price": 100,
            "end_date": "2026-08-01",
            "player": "Pikachu",
            "payment_status": "paid",
            "currency_code": "JPY",
            "certification_number": "12345678",
            "seller_email": "private@example.com",
            "buyer_id": "secret-user",
        }
        projected = MOD._project(row)
        self.assertEqual(projected["payment_status"], "paid")
        self.assertEqual(projected["currency_code"], "JPY")
        self.assertEqual(projected["certification_number"], "12345678")
        self.assertNotIn("seller_email", projected)
        self.assertNotIn("buyer_id", projected)

    def test_summary_never_promotes_closed_row_to_sale(self):
        summary = MOD.safe_summary()
        self.assertFalse(summary["closed_rows_promoted_to_sale"])
        self.assertFalse(summary["payment_semantics_proven"])
        self.assertFalse(summary["currency_semantics_proven"])
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
