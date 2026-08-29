import importlib.util
from pathlib import Path
import unittest


PATH = Path("mac/robot-kb-local/robot_kb_cardova_closed_api_probe.py")
SPEC = importlib.util.spec_from_file_location("cardova_closed_probe", PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


class CardovaClosedApiProbeTests(unittest.TestCase):
    def test_only_public_cardova_page_is_allowed(self):
        self.assertTrue(MOD._allowed_page_url(MOD.DEFAULT_PAGE_URL))
        self.assertFalse(MOD._allowed_page_url("http://www.cardova.co.jp/en/auction/close"))
        self.assertFalse(MOD._allowed_page_url("https://evil.example/en/auction/close"))

    def test_only_closed_list_api_response_is_targeted(self):
        good = "https://bg.cardova.co.jp/api/v1/auction/list?page=1&status=close&lang_code=en"
        self.assertTrue(MOD._target_closed_api_url(good))
        self.assertFalse(MOD._target_closed_api_url(good.replace("status=close", "status=live")))
        self.assertFalse(MOD._target_closed_api_url("https://bg.cardova.co.jp/api/v1/auction/select-list?status=close"))
        self.assertFalse(MOD._target_closed_api_url("https://evil.example/api/v1/auction/list?status=close"))

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

    def test_payload_summary_reports_fields_without_promoting_sale(self):
        payload = {"data": [{
            "ulid": "01ABC",
            "bid_price": 100,
            "end_date": "2026-08-01",
            "player": "Pikachu",
            "payment_status": "paid",
            "currency_code": "JPY",
        }]}
        summary = MOD._summarize_payload(payload)
        self.assertEqual(summary["closed_row_count"], 1)
        self.assertEqual(summary["status_field_names"], ["payment_status"])
        self.assertEqual(summary["currency_field_names"], ["currency_code"])

    def test_summary_is_browser_observation_only_and_never_promotes_sale(self):
        summary = MOD.safe_summary()
        self.assertTrue(summary["fresh_browser_context"])
        self.assertFalse(summary["cookies_supplied"])
        self.assertFalse(summary["storage_state_supplied"])
        self.assertFalse(summary["request_headers_captured"])
        self.assertFalse(summary["direct_api_replay_used"])
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
