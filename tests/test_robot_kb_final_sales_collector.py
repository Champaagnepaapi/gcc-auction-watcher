from __future__ import annotations

import unittest

from robot_kb.domain import ObservationType
from robot_kb.sidecar.final_sales import GCCCompletedSalesCollector
from robot_kb.sidecar.normalizers import normalize_gcc


T0 = "2026-08-14T20:00:00Z"
T1 = "2026-08-14T20:05:00Z"


class _FakeCollector:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []
        self.clock = lambda: T1

    def _request_page(self, params):
        self.calls.append(dict(params))
        return self.pages[params["page"]]


class GCCFinalSalesCollectorTests(unittest.TestCase):
    def sold_row(self):
        return {
            "id": "11111111-1111-1111-1111-111111111111",
            "status": "SOLD",
            "sellingType": "AUCTION",
            "soldPriceInCents": 2400,
            "soldAt": T0,
            "updatedAt": T0,
            "item": {
                "title": "Charizard 4/102",
                "gradingCompany": "PSA",
                "grade": "9",
                "serialNumber": "12345678",
                "collectible": {
                    "category": "Pokemon",
                    "language": "English",
                    "set": "Base Set",
                    "reference": "4/102",
                    "type": "CARDS",
                },
            },
        }

    def test_collector_requests_explicit_sold_scope_only(self):
        fake = _FakeCollector(
            {1: {"info": {"currentPage": 1, "nextPage": None}, "results": [self.sold_row()]}}
        )
        result = GCCCompletedSalesCollector(fake).collect(page_size=25, max_pages=2, max_records=50)
        self.assertEqual(len(result.records), 1)
        self.assertEqual(fake.calls[0]["sellingTypeGroup"], "AUCTION")
        self.assertEqual(fake.calls[0]["status"], "SOLD")
        self.assertNotIn("ON_SALE", fake.calls[0].values())

    def test_explicit_sold_row_becomes_sale_transaction(self):
        fake = _FakeCollector(
            {1: {"info": {"currentPage": 1, "nextPage": None}, "results": [self.sold_row()]}}
        )
        record = GCCCompletedSalesCollector(fake).collect().records[0]
        batch = normalize_gcc(record)
        observation = batch.observations[0]
        self.assertEqual(observation.observation_type, ObservationType.SALE_TRANSACTION)
        self.assertTrue(observation.genuine_sale_evidence)
        self.assertEqual(observation.event_at, T0)
        self.assertEqual(observation.prices[0].amount_minor, 2400)

    def test_sold_without_explicit_final_price_stays_snapshot(self):
        row = self.sold_row()
        row.pop("soldPriceInCents")
        row["priceInCents"] = 2400
        fake = _FakeCollector(
            {1: {"info": {"currentPage": 1, "nextPage": None}, "results": [row]}}
        )
        record = GCCCompletedSalesCollector(fake).collect().records[0]
        batch = normalize_gcc(record)
        observation = batch.observations[0]
        self.assertEqual(observation.observation_type, ObservationType.LISTING_SNAPSHOT)
        self.assertFalse(observation.genuine_sale_evidence)
        self.assertEqual(batch.sale_candidates_rejected, 1)


if __name__ == "__main__":
    unittest.main()
