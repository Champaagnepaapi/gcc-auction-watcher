from __future__ import annotations

import unittest

from robot_kb.domain import ObservationType
from robot_kb.sidecar.gcc_contract import (
    GCC_SOLD_PRICE_CONTRACT,
    normalize_gcc_source_contract,
)
from robot_kb.sidecar.models import RawSourceRecord


class GCCSoldContractTests(unittest.TestCase):
    def _record(self, *, status="SOLD", sold_at="2026-08-14T18:00:00Z"):
        payload = {
            "id": "11111111-1111-1111-1111-111111111111",
            "status": status,
            "sellingType": "AUCTION",
            "price": 240,
            "priceInCents": 24000,
            "soldAt": sold_at,
            "endTime": "2026-08-14T17:59:00Z",
            "item": {
                "id": "22222222-2222-2222-2222-222222222222",
                "title": "Charizard 4/102",
                "gradingCompany": "PSA",
                "grade": "9",
                "serialNumber": "12345678",
                "rectoImageKey": "front.jpg",
                "versoImageKey": "back.jpg",
                "collectible": {
                    "category": "Pokemon",
                    "type": "CARDS",
                    "language": "English",
                    "set": "Base Set",
                    "reference": "4/102",
                },
            },
        }
        return RawSourceRecord(
            source_code="gcc",
            source_name="GCC Marketplace",
            source_role="LISTING_PLATFORM",
            source_native_record_id=payload["id"],
            payload=payload,
            retrieved_at="2026-08-14T18:05:00Z",
            object_type="LISTING",
            external_native_id=payload["id"],
        )

    def test_sold_plus_sold_at_uses_price_as_proven_final_sale(self):
        raw = self._record()
        batch = normalize_gcc_source_contract(raw)
        observation = batch.observations[0]
        self.assertEqual(observation.observation_type, ObservationType.SALE_TRANSACTION)
        self.assertTrue(observation.genuine_sale_evidence)
        self.assertEqual(observation.event_at, "2026-08-14T18:00:00Z")
        self.assertEqual(observation.prices[0].amount_minor, 24000)
        self.assertEqual(
            observation.fact["final_price_evidence_method"], GCC_SOLD_PRICE_CONTRACT
        )
        # Immutable source payload remains untouched: provenance stays auditable.
        self.assertNotIn("soldPriceInCents", raw.payload)

    def test_ended_never_promotes_price_to_sale(self):
        batch = normalize_gcc_source_contract(self._record(status="ENDED"))
        observation = batch.observations[0]
        self.assertEqual(observation.observation_type, ObservationType.LISTING_SNAPSHOT)
        self.assertFalse(observation.genuine_sale_evidence)

    def test_sold_without_sold_at_never_promotes_price_to_sale(self):
        batch = normalize_gcc_source_contract(self._record(sold_at=None))
        observation = batch.observations[0]
        self.assertEqual(observation.observation_type, ObservationType.LISTING_SNAPSHOT)
        self.assertFalse(observation.genuine_sale_evidence)


if __name__ == "__main__":
    unittest.main()
