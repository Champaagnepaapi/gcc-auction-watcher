from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import v4_auction_item_discovery as discovery
import v4_auction_coverage_hardening as hardening


NOW = datetime(2026, 8, 31, 19, 30, tzinfo=timezone.utc)


def row(row_id: str, end_time: str) -> dict:
    return {
        "id": row_id,
        "status": "ON_SALE",
        "price": 50.0,
        "priceInCents": 5000,
        "sellingType": "AUCTION",
        "endTime": end_time,
        "item": {
            "title": "Pikachu",
            "gradingCompany": "PSA",
            "grade": "10",
            "collectible": {
                "category": "Pokemon",
                "language": "Japanese",
                "yearOfDistribution": "2023",
                "extension": "SV-P Promos",
                "set": "SV-P Promos",
                "reference": "120/SV-P",
                "type": "CARDS",
            },
        },
    }


def payload(rows: list[dict], *, next_page=None) -> dict:
    return {
        "info": {
            "currentPage": 1,
            "nextPage": next_page,
            "counts": {"total": len(rows), "auctionCount": len(rows)},
        },
        "results": rows,
    }


class Response:
    def __init__(self, data: dict):
        self.data = data
        self.headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class Getter:
    def __init__(self, payloads: list[dict]):
        self.payloads = list(payloads)
        self.calls = 0

    def __call__(self, *_args, **_kwargs):
        self.calls += 1
        if not self.payloads:
            raise AssertionError("unexpected API call")
        return Response(self.payloads.pop(0))


class AuctionHardeningDispatchTests(unittest.TestCase):
    def test_normal_verified_order_keeps_canonical_fast_path(self):
        getter = Getter(
            [
                payload(
                    [
                        row(
                            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                            "2026-08-31T20:40:00Z",
                        )
                    ],
                    next_page=2,
                )
            ]
        )

        result = hardening.discover_auction_api_lots_hardened(
            max_minutes=60,
            http_get=getter,
            page_size=100,
            now=NOW,
        )

        self.assertTrue(result.complete)
        self.assertEqual(result.reason, discovery.PRIMARY_END_REASON)
        self.assertTrue(result.order_verified)
        self.assertEqual(getter.calls, 1)

    def test_order_drift_retries_with_exhaustive_recovery_only(self):
        drifting = payload(
            [
                row(
                    "11111111-1111-1111-1111-111111111111",
                    "2026-08-31T20:20:00Z",
                ),
                row(
                    "22222222-2222-2222-2222-222222222222",
                    "2026-08-31T20:00:00Z",
                ),
            ],
            next_page=None,
        )
        getter = Getter([drifting, drifting])

        result = hardening.discover_auction_api_lots_hardened(
            max_minutes=60,
            http_get=getter,
            page_size=100,
            now=NOW,
        )

        self.assertTrue(result.complete)
        self.assertEqual(result.reason, discovery.PRIMARY_EXHAUSTED_REASON)
        self.assertFalse(result.order_verified)
        self.assertEqual(getter.calls, 2)
        self.assertEqual(len(result.lots), 2)

    def test_recovery_budget_expands_from_wider_api_total_hint(self):
        primary = SimpleNamespace(api_total=15049)

        budget = hardening._adaptive_recovery_max_pages(
            primary,
            page_size=100,
            base_max_pages=100,
        )

        self.assertEqual(budget, 153)

    def test_recovery_budget_keeps_hard_ceiling_for_large_inventory(self):
        primary = SimpleNamespace(api_total=50000)

        budget = hardening._adaptive_recovery_max_pages(
            primary,
            page_size=100,
            base_max_pages=100,
        )

        self.assertEqual(budget, 250)

    def test_order_drift_passes_adaptive_budget_to_exhaustive_recovery(self):
        drifting = payload(
            [
                row(
                    "11111111-1111-1111-1111-111111111111",
                    "2026-08-31T20:20:00Z",
                ),
                row(
                    "22222222-2222-2222-2222-222222222222",
                    "2026-08-31T20:00:00Z",
                ),
            ],
            next_page=2,
        )
        drifting["info"]["counts"]["total"] = 15049
        getter = Getter([drifting])
        recovered = SimpleNamespace(complete=False)

        with patch.object(
            hardening,
            "discover_auction_api_lots_exhaustive",
            return_value=recovered,
        ) as mocked_recovery:
            result = hardening.discover_auction_api_lots_hardened(
                max_minutes=60,
                http_get=getter,
                page_size=100,
                now=NOW,
            )

        self.assertIs(result, recovered)
        self.assertEqual(mocked_recovery.call_args.kwargs["max_pages"], 153)
        self.assertEqual(getter.calls, 1)


if __name__ == "__main__":
    unittest.main()
