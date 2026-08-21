from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping

import v4_kb_sold_watermark as sold


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.status_code = 200

    def json(self) -> Any:
        return self.payload


def final_row(native_id: str, sold_at: str) -> dict[str, Any]:
    return {
        "id": native_id,
        "status": "SOLD",
        "soldAt": sold_at,
        "priceInCents": 1000,
        "price": 10.0,
    }


def paged_get(dataset: list[dict[str, Any]]):
    def fake_get(
        url: str,
        params: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> FakeResponse:
        request = dict(params or {})
        page = int(request["page"])
        limit = int(request["limit"])
        start = (page - 1) * limit
        page_rows = dataset[start : start + limit]
        next_page = page + 1 if start + limit < len(dataset) else None
        return FakeResponse(
            {
                "info": {"currentPage": page, "nextPage": next_page},
                "results": page_rows,
            }
        )

    return fake_get


class SoldWaitingForPaymentMissingSoldAtTests(unittest.TestCase):
    def test_missing_sold_at_is_deferred_without_false_sale_or_crash(self):
        bootstrap = "2026-08-15T03:00:00Z"
        dataset = [
            {
                "id": "pending-no-date",
                "status": "WAITING_FOR_PAYMENT",
                "soldAt": None,
                "priceInCents": 1000,
            },
            final_row("final", "2026-08-15T04:00:00Z"),
            final_row("older", "2026-08-15T02:59:59Z"),
        ]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state.json"
            fixture = root / "fixture.json"
            manifest_path = root / "manifest.json"

            manifest = sold.fetch_sold_catchup_batch(
                state,
                fixture,
                manifest_path,
                bootstrap_since=bootstrap,
                http_get=paged_get(dataset),
            )

            fixture_rows = json.loads(fixture.read_text(encoding="utf-8"))
            self.assertEqual([item["id"] for item in fixture_rows], ["final"])
            self.assertFalse(manifest["caught_up"])
            self.assertTrue(manifest["watermark_blocked_by_nonfinal"])
            self.assertEqual(manifest["deferred_nonfinal_rows"], 1)
            self.assertEqual(manifest["deferred_nonfinal_unknown_time_rows"], 1)
            self.assertEqual(
                manifest["deferred_nonfinal_status_counts"],
                {"WAITING_FOR_PAYMENT": 1},
            )

            committed = sold.commit_sold_watermark(state, manifest_path)
            self.assertEqual(
                committed["committed_watermark_sold_at"],
                "2026-08-15T03:00:00.000000Z",
            )
            self.assertEqual(committed["pending_seen_ids"], ["final"])

    def test_missing_date_row_is_recovered_when_it_becomes_final_sold(self):
        bootstrap = "2026-08-15T03:00:00Z"
        first_dataset = [
            {"id": "pending-no-date", "status": "WAITING_FOR_PAYMENT", "soldAt": None},
            final_row("final", "2026-08-15T04:00:00Z"),
            final_row("older", "2026-08-15T02:59:59Z"),
        ]
        second_dataset = [
            final_row("pending-no-date", "2026-08-15T04:10:00Z"),
            final_row("final", "2026-08-15T04:00:00Z"),
            final_row("older", "2026-08-15T02:59:59Z"),
        ]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state.json"
            fixture = root / "fixture.json"
            manifest_path = root / "manifest.json"

            sold.fetch_sold_catchup_batch(
                state,
                fixture,
                manifest_path,
                bootstrap_since=bootstrap,
                http_get=paged_get(first_dataset),
            )
            sold.commit_sold_watermark(state, manifest_path)

            manifest = sold.fetch_sold_catchup_batch(
                state,
                fixture,
                manifest_path,
                bootstrap_since=bootstrap,
                http_get=paged_get(second_dataset),
            )
            fixture_rows = json.loads(fixture.read_text(encoding="utf-8"))
            self.assertEqual([item["id"] for item in fixture_rows], ["pending-no-date"])
            self.assertTrue(manifest["caught_up"])
            self.assertFalse(manifest["watermark_blocked_by_nonfinal"])

            committed = sold.commit_sold_watermark(state, manifest_path)
            self.assertEqual(
                committed["committed_watermark_sold_at"],
                "2026-08-15T04:10:00.000000Z",
            )
            self.assertEqual(committed["pending_seen_ids"], [])

    def test_invalid_nonfinal_sold_at_is_also_deferred_conservatively(self):
        dataset = [
            {
                "id": "pending-bad-date",
                "status": "WAITING_FOR_PAYMENT",
                "soldAt": "not-a-date",
            },
            final_row("older", "2026-08-15T02:59:59Z"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = sold.fetch_sold_catchup_batch(
                root / "state.json",
                root / "fixture.json",
                root / "manifest.json",
                bootstrap_since="2026-08-15T03:00:00Z",
                http_get=paged_get(dataset),
            )
            self.assertTrue(manifest["watermark_blocked_by_nonfinal"])
            self.assertEqual(manifest["deferred_nonfinal_unknown_time_rows"], 1)
            self.assertEqual(json.loads((root / "fixture.json").read_text()), [])


if __name__ == "__main__":
    unittest.main()
