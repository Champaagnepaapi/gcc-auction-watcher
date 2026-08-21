from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import v4_kb_sold_backfill as backfill


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self.payload


def sold_row(native_id: str, sold_at: datetime, price: float = 50.0) -> dict[str, Any]:
    return {
        "id": native_id,
        "status": "SOLD",
        "soldAt": sold_at.isoformat().replace("+00:00", "Z"),
        "price": price,
        "priceInCents": int(round(price * 100)),
        "item": {"id": f"item-{native_id}"},
    }


def waiting_row(native_id: str, sold_at: datetime | None = None) -> dict[str, Any]:
    return {
        "id": native_id,
        "status": "WAITING_FOR_PAYMENT",
        "soldAt": sold_at.isoformat().replace("+00:00", "Z") if sold_at else None,
        "price": 50.0,
        "priceInCents": 5000,
        "item": {"id": f"item-{native_id}"},
    }


class PagedApi:
    def __init__(self, rows: list[dict[str, Any]], page_size: int) -> None:
        self.rows = rows
        self.page_size = page_size
        self.pages: list[int] = []

    def __call__(self, url: str, params: Mapping[str, Any] = None, **kwargs: Any) -> FakeResponse:
        p = dict(params or {})
        page = int(p["page"])
        self.pages.append(page)
        start = (page - 1) * self.page_size
        results = self.rows[start : start + self.page_size]
        next_page = page + 1 if start + self.page_size < len(self.rows) else None
        return FakeResponse({"info": {"currentPage": page, "nextPage": next_page}, "results": results})


class SoldBackfillTests(unittest.TestCase):
    def test_initial_backfill_is_strictly_older_than_fresh_bootstrap(self) -> None:
        base = datetime(2026, 8, 15, 3, tzinfo=timezone.utc)
        rows = [
            sold_row("newer", base + timedelta(minutes=1)),
            sold_row("boundary", base),
            sold_row("old-1", base - timedelta(minutes=1)),
            sold_row("old-2", base - timedelta(minutes=2)),
            sold_row("old-3", base - timedelta(minutes=3)),
        ]
        api = PagedApi(rows, page_size=2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = backfill.fetch_sold_backfill_batch(
                root / "state.json",
                root / "fixture.json",
                root / "manifest.json",
                bootstrap_before=base.isoformat(),
                max_records=2,
                page_size=2,
                http_get=api,
            )
            fixture = json.loads((root / "fixture.json").read_text())
            self.assertEqual([row["id"] for row in fixture], ["old-1", "old-2"])
            self.assertNotIn("boundary", [row["id"] for row in fixture])
            self.assertEqual(manifest["records_count"], 2)
            self.assertFalse((root / "state.json").exists())

    def test_same_timestamp_boundary_is_drained_without_loss_or_duplicates(self) -> None:
        base = datetime(2026, 8, 15, 3, tzinfo=timezone.utc)
        shared = base - timedelta(minutes=10)
        rows = [
            sold_row("new", base + timedelta(minutes=1)),
            sold_row("a", shared),
            sold_row("b", shared),
            sold_row("c", shared),
            sold_row("older", shared - timedelta(minutes=1)),
        ]
        api = PagedApi(rows, page_size=2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state.json"
            fixture = root / "fixture.json"
            manifest = root / "manifest.json"

            backfill.fetch_sold_backfill_batch(
                state,
                fixture,
                manifest,
                bootstrap_before=base.isoformat(),
                max_records=2,
                page_size=2,
                http_get=api,
            )
            first = [row["id"] for row in json.loads(fixture.read_text())]
            backfill.commit_sold_backfill(state, manifest)

            backfill.fetch_sold_backfill_batch(
                state,
                fixture,
                manifest,
                bootstrap_before=base.isoformat(),
                max_records=2,
                page_size=2,
                http_get=api,
            )
            second = [row["id"] for row in json.loads(fixture.read_text())]
            self.assertEqual(set(first + second), {"a", "b", "c", "older"})
            self.assertEqual(len(first + second), len(set(first + second)))

    def test_state_advances_only_after_explicit_commit(self) -> None:
        base = datetime(2026, 8, 15, 3, tzinfo=timezone.utc)
        api = PagedApi([sold_row("old", base - timedelta(days=1))], page_size=1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state.json"
            manifest_path = root / "manifest.json"
            backfill.fetch_sold_backfill_batch(
                state,
                root / "fixture.json",
                manifest_path,
                bootstrap_before=base.isoformat(),
                page_size=1,
                http_get=api,
            )
            self.assertFalse(state.exists())
            committed = backfill.commit_sold_backfill(state, manifest_path)
            self.assertTrue(state.exists())
            self.assertLess(
                datetime.fromisoformat(committed["cursor_sold_at"].replace("Z", "+00:00")),
                base,
            )

    def test_waiting_for_payment_without_sold_at_is_deferred_not_emitted(self) -> None:
        base = datetime(2026, 8, 15, 3, tzinfo=timezone.utc)
        rows = [
            waiting_row("pending"),
            sold_row("newer", base + timedelta(minutes=1)),
            sold_row("old", base - timedelta(minutes=1)),
            sold_row("older", base - timedelta(minutes=2)),
        ]
        api = PagedApi(rows, page_size=4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = backfill.fetch_sold_backfill_batch(
                root / "state.json",
                root / "fixture.json",
                root / "manifest.json",
                bootstrap_before=base.isoformat(),
                page_size=4,
                http_get=api,
            )
            fixture = json.loads((root / "fixture.json").read_text())
            self.assertEqual([row["id"] for row in fixture], ["old", "older"])
            self.assertEqual(manifest["deferred_nonfinal_rows"], 1)
            self.assertEqual(
                manifest["deferred_nonfinal_status_counts"],
                {"WAITING_FOR_PAYMENT": 1},
            )

    def test_non_final_or_missing_price_rows_fail_closed(self) -> None:
        base = datetime(2026, 8, 15, 3, tzinfo=timezone.utc)
        bad = sold_row("bad", base - timedelta(days=1))
        bad["status"] = "ENDED"
        api = PagedApi([bad], page_size=1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(backfill.SoldBackfillError):
                backfill.fetch_sold_backfill_batch(
                    root / "state.json",
                    root / "fixture.json",
                    root / "manifest.json",
                    bootstrap_before=base.isoformat(),
                    page_size=1,
                    http_get=api,
                )


if __name__ == "__main__":
    unittest.main()
