from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "mac" / "robot-kb-local" / "robot_kb_fanatics_sales_history_probe.py"
SPEC = importlib.util.spec_from_file_location("robot_kb_fanatics_sales_history_probe", MODULE_PATH)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


class SearchContractTests(unittest.TestCase):
    def test_search_is_public_bounded_sales_history_query(self):
        url = probe.search_url("Pokemon Japanese PSA 10")
        parsed = urlparse(url)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "sales-history.fanaticscollect.com")
        query = parse_qs(parsed.query)
        self.assertEqual(query["title"], ["Pokemon Japanese PSA 10"])
        self.assertEqual(query["sort"], ["purchasePrice,desc"])
        with self.assertRaises(ValueError):
            probe.search_url("x")

    def test_only_fanatics_owned_hosts_are_body_capture_eligible(self):
        self.assertTrue(probe.fanatics_owned_host("https://sales-history.fanaticscollect.com/api/items"))
        self.assertTrue(probe.fanatics_owned_host("https://api.fanaticscollect.com/v1/items"))
        self.assertFalse(probe.fanatics_owned_host("https://example.com/api/items"))
        self.assertFalse(probe.fanatics_owned_host("https://fanaticscollect.com.example.com/api"))


class SanitizationTests(unittest.TestCase):
    def test_sensitive_json_fields_are_redacted_recursively(self):
        value = {
            "title": "Pokemon PSA 10",
            "authorizationToken": "SECRET",
            "nested": {
                "email": "collector@example.com",
                "purchasePrice": 130,
            },
        }
        safe = probe.sanitize_json(value)
        self.assertEqual(safe["authorizationToken"], "[REDACTED]")
        self.assertEqual(safe["nested"]["email"], "[REDACTED]")
        self.assertEqual(safe["nested"]["purchasePrice"], 130)
        self.assertNotIn("SECRET", json.dumps(safe))
        self.assertNotIn("collector@example.com", json.dumps(safe))

    def test_sensitive_query_values_are_redacted(self):
        url = probe.sanitized_url(
            "https://api.fanaticscollect.com/search?title=Pokemon&token=SECRET&session_id=ABC"
        )
        parsed = parse_qs(urlparse(url).query)
        self.assertEqual(parsed["title"], ["Pokemon"])
        self.assertEqual(parsed["token"], ["[REDACTED]"])
        self.assertEqual(parsed["session_id"], ["[REDACTED]"])
        self.assertNotIn("SECRET", url)
        self.assertNotIn("ABC", url)


class CandidateExtractionTests(unittest.TestCase):
    def test_nested_item_level_purchase_row_is_discovered(self):
        payload = {
            "data": {
                "items": [
                    {
                        "id": "sale-1",
                        "title": "2025 Pokemon Japanese Mega Dream ex N's Zoroark ex #242 PSA 10",
                        "purchasePrice": 13000,
                        "currency": "USD",
                        "soldAt": "2026-08-01T00:00:00Z",
                        "grader": "PSA",
                        "grade": "10",
                    }
                ]
            }
        }
        rows = probe.extract_sale_candidates(
            payload,
            source_url="https://sales-history.fanaticscollect.com/api/sold",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "sale-1")
        self.assertEqual(rows[0]["price"], 13000)
        self.assertEqual(rows[0]["currency"], "USD")
        self.assertEqual(rows[0]["grade"], "10")

    def test_aggregate_statistics_are_not_item_level_candidates(self):
        payload = {
            "title": "Pokemon PSA 10 summary",
            "price": 123.0,
            "averagePrice": 120.0,
            "medianPrice": 118.0,
        }
        self.assertEqual(
            probe.extract_sale_candidates(payload, source_url="https://sales-history.fanaticscollect.com/api/stats"),
            [],
        )

    def test_dom_sample_is_bounded_to_market_relevant_lines(self):
        body = "\n".join(
            [
                "Navigation",
                "Sold Items",
                "2025 Pokemon Japanese Pikachu PSA 10",
                "$125.00",
                "Unrelated footer",
            ]
        )
        lines = probe.interesting_dom_lines(body)
        self.assertIn("Sold Items", lines)
        self.assertIn("2025 Pokemon Japanese Pikachu PSA 10", lines)
        self.assertIn("$125.00", lines)
        self.assertNotIn("Unrelated footer", lines)


class SafetyTests(unittest.TestCase):
    def test_summary_never_promotes_or_writes_a_sale(self):
        summary = probe.safe_summary("Pokemon")
        self.assertEqual(summary["mode"], "READ_ONLY_FANATICS_SALES_HISTORY_PROBE")
        self.assertTrue(summary["public_anonymous_session"])
        self.assertFalse(summary["credentials_used"])
        self.assertFalse(summary["robot_kb_write"])
        self.assertFalse(summary["sale_transaction_stored"])
        self.assertFalse(summary["genuine_sale_evidence_promoted"])
        self.assertFalse(summary["v4_economic_use"])
        self.assertFalse(summary["automatic_purchase"])
        self.assertFalse(summary["automatic_bid"])
        self.assertFalse(summary["automatic_checkout"])
        self.assertFalse(summary["automatic_payment"])

    def test_script_has_no_robot_kb_or_secret_dependency(self):
        text = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("KnowledgeBase", text)
        self.assertNotIn("ROBOT_KB_DATABASE_URL", text)
        self.assertNotIn("find-generic-password", text)
        self.assertNotIn("storage_state=", text)
        self.assertNotIn("persistent_context", text)


if __name__ == "__main__":
    unittest.main()
