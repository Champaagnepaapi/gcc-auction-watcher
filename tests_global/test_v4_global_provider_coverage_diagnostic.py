from __future__ import annotations

import unittest

import watcher
import v4_canonical_multimarket as multimarket
import v4_global_provider_coverage_diagnostic as diagnostic
from v4_global_market_core import CommercialIdentity


class ProviderCoverageDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.lot = watcher.Lot(
            url="https://example.invalid/card",
            title="Raikou",
            current_price=1.0,
            source_type="FIXED_PRICE",
            grader="PSA",
            grade="10",
            card_set="VSTAR Universe",
            card_number="218/172",
            language="Japanese",
        )
        self.canonical = multimarket.CanonicalCard(
            status="EXACT",
            card_id="S12a-218",
            set_id="S12a",
            set_name="VSTAR Universe",
            local_id="218",
            full_number="218/172",
            name="Raikou",
            language_code="ja",
            variants={},
            reason="TEST",
            unique_name_number=False,
        )

    def candidate(self, **overrides):
        row = {
            "id": "pt-1",
            "name": "Raikou",
            "cardNumber": "218/172",
            "game": "pokemon-japanese",
            "productType": "single",
            "set": {"id": "provider-s12a", "name": "VSTAR Universe", "slug": "vstar-universe"},
            "prices": {"ebay": {"PSA_10": {"avg": 100, "low": 90, "high": 110, "saleCount": 4}}},
        }
        row.update(overrides)
        return row

    def test_exact_candidate_is_visible_but_does_not_change_identity(self):
        self.assertEqual(
            diagnostic.classify_poketrace_candidate(
                self.lot, self.canonical, self.candidate()
            ),
            "EXACT",
        )

    def test_set_namespace_failure_is_distinct(self):
        row = self.candidate(set={"id": "opaque-777", "name": "Provider Universe", "slug": "provider-universe"})
        self.assertEqual(
            diagnostic.classify_poketrace_candidate(self.lot, self.canonical, row),
            "REJECT_SET_NAMESPACE",
        )

    def test_name_failure_precedes_set_bridge(self):
        row = self.candidate(name="Entei")
        self.assertEqual(
            diagnostic.classify_poketrace_candidate(self.lot, self.canonical, row),
            "REJECT_NAME",
        )

    def test_sanitizer_keeps_only_bounded_tier_summary(self):
        row = self.candidate(secret="must-not-leak", prices={"ebay": {"PSA_10": {"avg": 100, "saleCount": 4, "raw": "hidden"}}})
        payload = diagnostic.sanitize_poketrace_candidate(self.lot, self.canonical, row)
        self.assertNotIn("secret", payload)
        self.assertNotIn("prices", payload)
        self.assertEqual(payload["target_tier_summary"]["sale_count"], 4)
        self.assertTrue(payload["target_tier_summary"]["avg_present"])

    def test_ppt_present_conflicting_catalog_coordinate_stays_no_match(self):
        identity = CommercialIdentity(
            name="Raikou",
            set_name="VSTAR Universe",
            number="218/172",
            language="ja",
            grader="PSA",
            grade="10",
        )
        row = {
            "externalCatalogId": "wrong-card",
            "name": "Raikou",
            "setName": "VSTAR Universe",
            "cardNumber": "218",
            "language": "japanese",
        }
        verdict = diagnostic._ppt_candidate_verdict(identity, self.canonical, row)
        self.assertTrue(verdict.startswith("CLEAN_NO_MATCH"))


if __name__ == "__main__":
    unittest.main()
