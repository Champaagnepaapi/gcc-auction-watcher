from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "mac" / "robot-kb-local" / "robot_kb_fanatics_currency_probe.py"
SPEC = importlib.util.spec_from_file_location("robot_kb_fanatics_currency_probe", MODULE_PATH)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


class CurrencyProbeTests(unittest.TestCase):
    def test_only_exact_public_fanatics_listing_urls_are_allowed(self):
        self.assertTrue(probe.validate_listing_url("https://www.fanaticscollect.com/premier/abc/title"))
        with self.assertRaises(ValueError):
            probe.validate_listing_url("https://evil.example/premier/abc")
        with self.assertRaises(ValueError):
            probe.validate_listing_url("https://www.fanaticscollect.com/account")

    def test_explicit_iso_currency_next_to_price_is_detected(self):
        hits = probe.currency_hits({"price": 198000, "currencyCode": "USD"})
        kinds = {item["kind"] for item in hits}
        self.assertIn("currency_key", kinds)
        self.assertIn("iso_currency_value", kinds)
        self.assertIn("price_currency_object", kinds)

    def test_dollar_glyph_is_not_currency_proof(self):
        hits = probe.currency_hits({"priceText": "$198,000", "amount": 198000})
        self.assertEqual(hits, [])

    def test_unrelated_iso_currency_string_is_visible_but_not_fabricated(self):
        hits = probe.currency_hits({"wallet": {"unit": "GBP"}})
        self.assertTrue(any(hit.get("value") == "GBP" for hit in hits))

    def test_summary_remains_read_only(self):
        summary = probe.safe_summary()
        self.assertFalse(summary["currency_inferred_from_dollar_glyph"])
        self.assertFalse(summary["robot_kb_write"])
        self.assertFalse(summary["sale_transaction_stored"])
        self.assertFalse(summary["v4_economic_use"])
        self.assertFalse(summary["automatic_purchase"])
        self.assertFalse(summary["automatic_bid"])
        self.assertFalse(summary["automatic_checkout"])
        self.assertFalse(summary["automatic_payment"])

    def test_script_has_no_secret_or_database_dependency(self):
        text = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("ROBOT_KB_DATABASE_URL", text)
        self.assertNotIn("Authorization", text)
        self.assertNotIn("find-generic-password", text)
        self.assertNotIn("KnowledgeBase(", text)


if __name__ == "__main__":
    unittest.main()
