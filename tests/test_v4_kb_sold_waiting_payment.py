from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping

import v4_kb_sold_watermark as sold


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self.payload


def row(native_id: str, status: str, sold_at: str, price_cents: int = 1000) -> dict[str, Any]:
    return {
        "id": native_id,
        "status": status,
        "soldAt": sold_at,
        "priceInCents": price_cents,
        "price": price_cents / 100.0,
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


class SoldWaitingForPaymentTests(unittest.TestCase):
    def test_waiting_for_payment_is_not_a_sale_and_blocks_watermark(self):
        bootstrap = "2026-08-15T03:00:00Z"
        dataset = [
            row("pending", "WAITING_FOR_PAYMENT", "2026-08-15T04:10:00Z"),
            row("final", "SOLD", "2026-08-15T04:00:00Z"),
            row("older", "SOLD", "2026-08-15T02:59:59Z"),
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

    def test_deferred_row_is_ingested_once_it_becomes_final_sold(self):
        bootstrap = "2026-08-15T03:00:00Z"
        first_dataset = [
            row("pending", "WAITING_FOR_PAYMENT", "2026-08-15T04:10:00Z"),
            row("final", "SOLD", "2026-08-15T04:00:00Z"),
            row("older", "SOLD", "2026-08-15T02:59:59Z"),
        ]
        second_dataset = [
            row("pending", "SOLD", "2026-08-15T04:10:00Z"),
            row("final", "SOLD", "2026-08-15T04:00:00Z"),
            row("older", "SOLD", "2026-08-15T02:59:59Z"),
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
            self.assertEqual([item["id"] for item in fixture_rows], ["pending"])
            self.assertTrue(manifest["caught_up"])
            self.assertFalse(manifest["watermark_blocked_by_nonfinal"])

            committed = sold.commit_sold_watermark(state, manifest_path)
            self.assertEqual(
                committed["committed_watermark_sold_at"],
                "2026-08-15T04:10:00.000000Z",
            )
            self.assertEqual(committed["pending_seen_ids"], [])

    def test_unknown_nonfinal_status_still_fails_closed(self):
        dataset = [row("ended", "ENDED", "2026-08-15T04:00:00Z")]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(sold.SoldWatermarkError):
                sold.fetch_sold_catchup_batch(
                    root / "state.json",
                    root / "fixture.json",
                    root / "manifest.json",
                    bootstrap_since="2026-08-15T03:00:00Z",
                    http_get=paged_get(dataset),
                )


if __name__ == "__main__":
    unittest.main()
