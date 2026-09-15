from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "mac" / "robot-kb-local" / "robot_kb_comc_sales_history_probe.py"
SPEC = importlib.util.spec_from_file_location("robot_kb_comc_sales_history_probe", MODULE_PATH)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


class ComcSalesHistoryProbeTests(unittest.TestCase):
    def test_only_public_comc_https_urls_are_allowed(self):
        self.assertTrue(probe._allowed_url("https://www.comc.com/Cards/Pokemon/example"))
        self.assertTrue(probe._allowed_url("https://comc.com/Cards/Pokemon/example"))
        self.assertFalse(probe._allowed_url("http://www.comc.com/Cards/Pokemon/example"))
        self.assertFalse(probe._allowed_url("https://example.com/Cards/Pokemon/example"))

    def test_date_and_price_are_required_for_diagnostic_sale_candidate(self):
        self.assertIsNone(probe._item_level_sale_candidate({"price": 12.5}))
        self.assertIsNone(probe._item_level_sale_candidate({"soldDate": "2026-01-01"}))
        candidate = probe._item_level_sale_candidate(
            {
                "saleId": "abc",
                "soldDate": "2026-01-01T00:00:00Z",
                "salePrice": 12.5,
                "currency": "USD",
            }
        )
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate["currency_fields"]["currency"], "USD")

    def test_candidate_is_not_a_sold_classifier(self):
        summary = probe.safe_summary()
        self.assertFalse(summary["sold_out_treated_as_sale"])
        self.assertFalse(summary["historical_chart_treated_as_sale"])
        self.assertFalse(summary["sale_transaction_stored"])

    def test_sanitizer_drops_sensitive_named_fields(self):
        result = probe._sanitize(
            {
                "price": 10,
                "cookie": "x",
                "authorization": "y",
                "sessionToken": "z",
                "nested": {"password": "p", "currency": "USD"},
            }
        )
        self.assertEqual(result["price"], 10)
        self.assertNotIn("cookie", result)
        self.assertNotIn("authorization", result)
        self.assertNotIn("sessionToken", result)
        self.assertNotIn("password", result["nested"])
        self.assertEqual(result["nested"]["currency"], "USD")

    def test_summary_is_strictly_read_only(self):
        summary = probe.safe_summary()
        self.assertTrue(summary["public_anonymous_only"])
        self.assertFalse(summary["credentials_used"])
        self.assertFalse(summary["cookies_supplied"])
        self.assertFalse(summary["authentication_headers_supplied"])
        self.assertFalse(summary["robot_kb_write"])
        self.assertFalse(summary["v4_economic_use"])
        self.assertFalse(summary["automatic_purchase"])
        self.assertFalse(summary["automatic_bid"])
        self.assertFalse(summary["automatic_offer"])
        self.assertFalse(summary["automatic_checkout"])
        self.assertFalse(summary["automatic_payment"])

    def test_script_contains_no_robot_kb_or_login_dependency(self):
        text = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("ROBOT_KB_DATABASE_URL", text)
        self.assertNotIn("KnowledgeBase(", text)
        self.assertNotIn("find-generic-password", text)
        self.assertNotIn("storage_state=", text)
        self.assertNotIn("Authorization\":", text)


if __name__ == "__main__":
    unittest.main()
