import unittest
from datetime import datetime, timezone
from dataclasses import asdict

from v4_global_market_core import CommercialIdentity
from v4_global_marketplace_scan import ScanStatus
import v4_global_marketplace_notify as runner


class PipelineReportTests(unittest.TestCase):
    def test_report_distinguishes_discovery_identity_value_cost_and_decision(self):
        identity = CommercialIdentity("Pikachu", "151", "025/165", "ja", "PSA", "10")
        card = {"identity": asdict(identity), "offers": [
            {"market": "gcc", "source_id": "1", "source_url": "https://gradedcardcenter.com/item/1", "all_in_eur": 20},
            {"market": "magi", "source_id": "2", "source_url": "https://magi.camp/items/2", "all_in_eur": None}],
            "economic_confirmation": {"external_canonical": {"status": "EXACT", "card_id": "SV2a-025"},
                "ppt": {"status": "MATCHED"}, "poketrace": {"status": "CLEAN_NO_MATCH"},
                "decision": {"status": "MULTIMARKET_CONFIRMED", "would_notify": True,
                    "best_market": "gcc", "source_url": "https://gradedcardcenter.com/item/1"}}}
        statuses = [ScanStatus("gcc", "OK", candidates=10, exact=3, complete=True),
                    ScanStatus("magi", "OK", candidates=20, exact=2, complete=False)]
        summary = runner.pipeline_report(statuses, [card])
        self.assertEqual(summary["gcc"]["would_notify"], 1)
        self.assertEqual(summary["magi"]["would_notify"], 0)
        self.assertEqual(summary["magi"]["cost_unproven"], 1)
        self.assertEqual(summary["magi"]["canonical_exact"], 1)
        self.assertEqual(summary["magi"]["value_matched"], 1)
        self.assertFalse(summary["magi"]["pagination_complete"])
        self.assertEqual(summary["gcc"]["selected"], 1)
        self.assertEqual(summary["gcc"]["discovered_identities"], 3)
        self.assertEqual(summary, runner.pipeline_report(statuses, [card]))

    def test_shared_valuation_does_not_claim_every_offer_as_notified(self):
        summary = runner.pipeline_report([ScanStatus("fanatics", "UNAVAILABLE")], [])
        self.assertEqual(summary["fanatics"]["selected"], 0)
        self.assertEqual(summary["fanatics"]["discovery_status"], "UNAVAILABLE")
        self.assertEqual(summary["fanatics"]["would_notify"], 0)


if __name__ == "__main__":
    unittest.main()
