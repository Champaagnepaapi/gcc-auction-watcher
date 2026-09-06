from __future__ import annotations

import inspect
import unittest
from datetime import datetime, timezone
from unittest import mock

import watcher
import v4_canonical_multimarket as multimarket
import run_watcher_multimarket_resilient as resilient


class PokeTraceRecallPolicyTests(unittest.TestCase):
    def test_resilient_bootstrap_no_longer_installs_degenerate_aggregate_guard(self):
        source = inspect.getsource(resilient)
        self.assertNotIn("install_v4_poketrace_aggregate_quality_guard", source)

    def test_high_volume_exact_grade_aggregate_without_range_is_strong(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/magneton",
            title="PSA 10 Magneton",
            current_price=30.0,
            source_type="fixed",
            grader="PSA",
            grade="10",
            card_set="Super Electric Breaker",
            card_number="#112/106",
            language="Japanese",
        )
        canonical = multimarket.CanonicalCard(
            status="EXACT",
            card_id="SV8-112",
            set_id="SV8",
            set_name="Super Electric Breaker",
            local_id="112",
            full_number="112/106",
            name="Magneton",
            language_code="ja",
        )
        payload = {
            "data": [
                {
                    "id": "provider-card",
                    "name": "Magneton",
                    "cardNumber": "112/106",
                    "currency": "USD",
                    "prices": {
                        "ebay": {
                            "PSA_10": {
                                "avg": 44.74,
                                "saleCount": 305,
                            }
                        }
                    },
                }
            ]
        }
        budget = multimarket.RequestBudget()

        with mock.patch.object(multimarket, "POKETRACE_ENABLED", True), \
             mock.patch.object(multimarket, "POKETRACE_API_KEY", "test"), \
             mock.patch.object(multimarket, "_ensure_poketrace_auth", return_value=(True, "PRO")), \
             mock.patch.object(multimarket, "_paced_poketrace_get", return_value=(200, payload, {})), \
             mock.patch.object(multimarket, "_candidate_exact_for_canonical", return_value=True), \
             mock.patch.object(multimarket, "_to_eur", side_effect=lambda value, unit: value):
            evidence = multimarket._poketrace_evidence(
                lot, canonical, budget, datetime.now(timezone.utc)
            )

        self.assertEqual(evidence.status, watcher.EXTERNAL_MATCHED)
        self.assertEqual(evidence.strength, watcher.EVIDENCE_STRONG)
        self.assertIsNotNone(evidence.estimate)
        self.assertEqual(evidence.estimate.central, 44.74)
        self.assertEqual(evidence.estimate.exact_grade_count, 305)
        self.assertEqual(evidence.estimate.low, 44.74)
        self.assertEqual(evidence.estimate.high, 44.74)


if __name__ == "__main__":
    unittest.main()
