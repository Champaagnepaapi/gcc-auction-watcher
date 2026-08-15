from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import v4_kb_sold_watermark as sold


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def sold_row(native_id: str, sold_at: str, *, price_cents: int = 1234) -> dict[str, Any]:
    return {
        "id": native_id,
        "status": "SOLD",
        "soldAt": sold_at,
        "priceInCents": price_cents,
        "price": price_cents / 100.0,
    }


def rows(prefix: str, start: datetime, count: int) -> list[dict[str, Any]]:
    return [
        sold_row(
            f"{prefix}-{index}",
            (start - timedelta(seconds=index)).isoformat().replace("+00:00", "Z"),
        )
        for index in range(count)
    ]


class SoldWatermarkTests(unittest.TestCase):
    def _paged_get(self, dataset: list[dict[str, Any]], calls: list[dict[str, Any]]):
        def fake_get(
            url: str,
            params: Mapping[str, Any] | None = None,
            **kwargs: Any,
        ) -> FakeResponse:
            request = dict(params or {})
            calls.append(request)
            page = int(request["page"])
            limit = int(request["limit"])
            start = (page - 1) * limit
            page_rows = dataset[start : start + limit]
            next_page = page + 1 if start + limit < len(dataset) else None
            return FakeResponse(
                {
                    "info": {
                        "currentPage": page,
                        "nextPage": next_page,
                    },
                    "results": page_rows,
                }
            )

        return fake_get

    def test_drains_1000_sale_spike_without_gap_across_runs(self):
        bootstrap = "2026-08-15T03:00:00Z"
        dataset = rows(
            "spike",
            datetime(2026, 8, 15, 4, 0, 0, tzinfo=timezone.utc),
            1000,
        )
        dataset.extend(
            [
                sold_row("boundary", bootstrap),
                sold_row("older", "2026-08-15T02:59:59Z"),
            ]
        )
        calls: list[dict[str, Any]] = []
        fake_get = self._paged_get(dataset, calls)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "sold_state.json"
            fixture = root / "sold_fixture.json"
            manifest = root / "sold_manifest.json"
            collected: set[str] = set()

            counts = []
            for _ in range(3):
                sold.fetch_sold_catchup_batch(
                    state,
                    fixture,
                    manifest,
                    bootstrap_since=bootstrap,
                    max_records=400,
                    page_size=100,
                    max_scan_pages=100,
                    http_get=fake_get,
                )
                batch = json.loads(fixture.read_text(encoding="utf-8"))
                counts.append(len(batch))
                collected.update(row["id"] for row in batch)
                sold.commit_sold_watermark(state, manifest)

            self.assertEqual(counts, [400, 400, 201])
            self.assertEqual(
                collected,
                {f"spike-{index}" for index in range(1000)} | {"boundary"},
            )
            state_payload = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(state_payload["pending_seen_ids"], [])
            self.assertEqual(
                state_payload["committed_watermark_sold_at"],
                "2026-08-15T04:00:00.000000Z",
            )

    def test_new_sales_arriving_while_backlog_drains_are_preserved(self):
        bootstrap = "2026-08-15T03:00:00Z"
        dataset = rows(
            "oldspike",
            datetime(2026, 8, 15, 4, 0, 0, tzinfo=timezone.utc),
            1000,
        )
        dataset.append(sold_row("boundary", bootstrap))
        calls: list[dict[str, Any]] = []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state.json"
            fixture = root / "fixture.json"
            manifest = root / "manifest.json"
            collected: set[str] = set()

            first = sold.fetch_sold_catchup_batch(
                state,
                fixture,
                manifest,
                bootstrap_since=bootstrap,
                max_records=400,
                http_get=self._paged_get(dataset, calls),
                max_scan_pages=100,
            )
            self.assertTrue(first["cap_reached"])
            collected.update(row["id"] for row in json.loads(fixture.read_text()))
            sold.commit_sold_watermark(state, manifest)

            dataset[:0] = rows(
                "fresh",
                datetime(2026, 8, 15, 5, 0, 0, tzinfo=timezone.utc),
                50,
            )

            for _ in range(2):
                sold.fetch_sold_catchup_batch(
                    state,
                    fixture,
                    manifest,
                    bootstrap_since=bootstrap,
                    max_records=400,
                    http_get=self._paged_get(dataset, calls),
                    max_scan_pages=100,
                )
                collected.update(row["id"] for row in json.loads(fixture.read_text()))
                sold.commit_sold_watermark(state, manifest)

            expected = (
                {f"oldspike-{index}" for index in range(1000)}
                | {f"fresh-{index}" for index in range(50)}
                | {"boundary"}
            )
            self.assertEqual(collected, expected)
            state_payload = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(state_payload["pending_seen_ids"], [])
            self.assertEqual(
                state_payload["committed_watermark_sold_at"],
                "2026-08-15T05:00:00.000000Z",
            )

    def test_state_only_advances_on_explicit_commit(self):
        bootstrap = "2026-08-15T03:00:00Z"
        dataset = [
            sold_row("new", "2026-08-15T03:30:00Z"),
            sold_row("older", "2026-08-15T02:59:59Z"),
        ]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state.json"
            fixture = root / "fixture.json"
            manifest = root / "manifest.json"

            sold.fetch_sold_catchup_batch(
                state,
                fixture,
                manifest,
                bootstrap_since=bootstrap,
                http_get=self._paged_get(dataset, []),
            )
            self.assertFalse(state.exists())

            committed = sold.commit_sold_watermark(state, manifest)
            self.assertTrue(state.exists())
            self.assertEqual(
                committed["committed_watermark_sold_at"],
                "2026-08-15T03:30:00.000000Z",
            )

    def test_http_failure_leaves_existing_state_unchanged(self):
        bootstrap = "2026-08-15T03:00:00Z"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state.json"
            initial = sold._new_state_from_bootstrap(bootstrap)
            state.write_text(json.dumps(initial), encoding="utf-8")

            def fake_get(*args: Any, **kwargs: Any) -> FakeResponse:
                return FakeResponse({}, status_code=503)

            with self.assertRaises(sold.SoldWatermarkError):
                sold.fetch_sold_catchup_batch(
                    state,
                    root / "fixture.json",
                    root / "manifest.json",
                    bootstrap_since=bootstrap,
                    http_get=fake_get,
                )

            self.assertEqual(json.loads(state.read_text()), initial)

    def test_corrupt_existing_state_fails_closed_instead_of_rebootstrapping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state.json"
            state.write_text("{not-json", encoding="utf-8")
            with self.assertRaises(sold.SoldWatermarkError):
                sold.fetch_sold_catchup_batch(
                    state,
                    root / "fixture.json",
                    root / "manifest.json",
                    bootstrap_since="2026-08-15T03:00:00Z",
                    http_get=lambda *a, **k: FakeResponse({}),
                )

    def test_non_final_sold_contract_fails_closed(self):
        invalid_rows = [
            {"id": "not-sold", "status": "ENDED", "soldAt": "2026-08-15T04:00:00Z", "priceInCents": 100},
            {"id": "no-time", "status": "SOLD", "priceInCents": 100},
            {"id": "no-price", "status": "SOLD", "soldAt": "2026-08-15T04:00:00Z"},
        ]
        for invalid in invalid_rows:
            with self.subTest(invalid=invalid["id"]):
                dataset = [invalid]
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    with self.assertRaises(sold.SoldWatermarkError):
                        sold.fetch_sold_catchup_batch(
                            root / "state.json",
                            root / "fixture.json",
                            root / "manifest.json",
                            bootstrap_since="2026-08-15T03:00:00Z",
                            http_get=self._paged_get(dataset, []),
                        )

    def test_explicit_most_recent_sold_scope_and_400_cap(self):
        bootstrap = "2026-08-15T03:00:00Z"
        dataset = rows(
            "sale",
            datetime(2026, 8, 15, 4, 0, 0, tzinfo=timezone.utc),
            401,
        )
        calls: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = sold.fetch_sold_catchup_batch(
                root / "state.json",
                root / "fixture.json",
                root / "manifest.json",
                bootstrap_since=bootstrap,
                max_records=400,
                http_get=self._paged_get(dataset, calls),
            )
            self.assertEqual(manifest["records_count"], 400)
            self.assertTrue(manifest["cap_reached"])
            self.assertGreaterEqual(len(calls), 1)
            for params in calls:
                self.assertEqual(params["sellingTypeGroup"], "AUCTION")
                self.assertEqual(params["status"], "SOLD")
                self.assertEqual(params["sortType"], "MOST_RECENT")
                self.assertEqual(params["limit"], 100)


if __name__ == "__main__":
    unittest.main()
