from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping

import v4_kb_fixed_rotation as rotation
import watcher


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.headers = {}

    def json(self) -> Any:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def fake_gcc_row(native_id: str, *, price_cents: int = 4500) -> dict[str, Any]:
    return {
        "id": native_id,
        "status": "ON_SALE",
        "sellingType": "FIXED_PRICE",
        "priceInCents": price_cents,
        "price": price_cents / 100.0,
        "item": {
            "id": f"item-{native_id}",
            "title": f"Card {native_id}",
            "gradingCompany": "PSA",
            "grade": "10",
            "collectible": {
                "category": "Pokemon",
                "type": "CARDS",
                "language": "French",
            },
        },
    }


class FixedRotationTests(unittest.TestCase):
    def test_progression_1_4_to_5_8(self):
        calls: list[dict[str, Any]] = []

        def fake_get(url: str, params: Mapping[str, Any] = None, **kwargs: Any) -> FakeResponse:
            params = dict(params or {})
            page = params.get("page", 1)
            calls.append(params)
            total_items = 6800  # 68 pages
            next_page = page + 1 if page < 68 else None
            return FakeResponse({
                "info": {
                    "currentPage": page,
                    "nextPage": next_page,
                    "counts": {"fixedPriceCount": total_items},
                },
                "results": [fake_gcc_row(f"p{page}-i{i}") for i in range(10)],
            })

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_file = root / "rotation_state.json"
            fixture_file = root / "fixture.json"
            manifest_file = root / "manifest.json"

            # Run 1: starts at page 1, collects 1..4
            manifest1 = rotation.fetch_fixed_rotation_batch(
                state_file,
                fixture_file,
                manifest_file,
                pages_per_run=4,
                page_size=100,
                http_get=fake_get,
            )
            self.assertEqual(manifest1["start_page"], 1)
            self.assertEqual(manifest1["last_page"], 4)
            self.assertEqual(manifest1["pages_fetched"], 4)
            self.assertEqual(manifest1["total_pages_seen"], 68)
            self.assertEqual([c["page"] for c in calls], [1, 2, 3, 4])

            # Commit Run 1
            committed_state1 = rotation.commit_rotation_cursor(state_file, manifest_file)
            self.assertEqual(committed_state1["last_page"], 4)

            # Run 2: starts at page 5, collects 5..8
            calls.clear()
            manifest2 = rotation.fetch_fixed_rotation_batch(
                state_file,
                fixture_file,
                manifest_file,
                pages_per_run=4,
                page_size=100,
                http_get=fake_get,
            )
            self.assertEqual(manifest2["start_page"], 5)
            self.assertEqual(manifest2["last_page"], 8)
            self.assertEqual([c["page"] for c in calls], [5, 6, 7, 8])

            # Commit Run 2
            committed_state2 = rotation.commit_rotation_cursor(state_file, manifest_file)
            self.assertEqual(committed_state2["last_page"], 8)

    def test_wrap_at_inventory_end(self):
        calls: list[dict[str, Any]] = []

        def fake_get(url: str, params: Mapping[str, Any] = None, **kwargs: Any) -> FakeResponse:
            params = dict(params or {})
            page = params.get("page", 1)
            calls.append(params)
            total_items = 600  # 6 pages total
            next_page = page + 1 if page < 6 else None
            return FakeResponse({
                "info": {
                    "currentPage": page,
                    "nextPage": next_page,
                    "counts": {"fixedPriceCount": total_items},
                },
                "results": [fake_gcc_row(f"p{page}-i{i}") for i in range(5)],
            })

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_file = root / "rotation_state.json"
            fixture_file = root / "fixture.json"
            manifest_file = root / "manifest.json"

            # Set state to last_page=4 with total 6 pages seen
            state_file.write_text(
                json.dumps({
                    "schema_version": 1,
                    "last_page": 4,
                    "total_pages_seen": 6,
                    "updated_at": "2026-08-14T12:00:00Z",
                }),
                encoding="utf-8",
            )

            manifest = rotation.fetch_fixed_rotation_batch(
                state_file,
                fixture_file,
                manifest_file,
                pages_per_run=4,
                page_size=100,
                http_get=fake_get,
            )
            self.assertEqual(manifest["start_page"], 5)
            self.assertEqual(manifest["last_page"], 2)
            self.assertEqual([c["page"] for c in calls], [5, 6, 1, 2])

            committed = rotation.commit_rotation_cursor(state_file, manifest_file)
            self.assertEqual(committed["last_page"], 2)

    def test_pokemon_and_cards_filters_always_present(self):
        calls: list[dict[str, Any]] = []

        def fake_get(url: str, params: Mapping[str, Any] = None, **kwargs: Any) -> FakeResponse:
            params = dict(params or {})
            calls.append(params)
            return FakeResponse({
                "info": {"currentPage": params.get("page", 1), "nextPage": 2},
                "results": [fake_gcc_row("c1")],
            })

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rotation.fetch_fixed_rotation_batch(
                root / "state.json",
                root / "fixture.json",
                root / "manifest.json",
                pages_per_run=4,
                page_size=100,
                http_get=fake_get,
            )

            self.assertEqual(len(calls), 4)
            for param_dict in calls:
                self.assertEqual(param_dict.get("sellingTypes"), "FIXED_PRICE")
                self.assertEqual(param_dict.get("categories"), "Pokemon")
                self.assertEqual(param_dict.get("itemTypes"), "CARDS")
                self.assertEqual(param_dict.get("limit"), 100)

    def test_failed_page_fetch_does_not_advance_cursor(self):
        call_count = 0

        def fake_get(url: str, params: Mapping[str, Any] = None, **kwargs: Any) -> FakeResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return FakeResponse({}, status_code=502)
            return FakeResponse({
                "info": {"currentPage": 1, "nextPage": 2},
                "results": [fake_gcc_row("c1")],
            })

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_file = root / "state.json"
            initial_state = {
                "schema_version": 1,
                "last_page": 0,
                "total_pages_seen": 68,
                "updated_at": "2026-08-14T10:00:00Z",
            }
            state_file.write_text(json.dumps(initial_state), encoding="utf-8")

            with self.assertRaises(rotation.RotationError):
                rotation.fetch_fixed_rotation_batch(
                    state_file,
                    root / "fixture.json",
                    root / "manifest.json",
                    pages_per_run=4,
                    http_get=fake_get,
                )

            # State was never touched
            current_state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(current_state["last_page"], 0)

    def test_malformed_page_does_not_advance_cursor(self):
        def fake_get_wrong_page(url: str, params: Mapping[str, Any] = None, **kwargs: Any) -> FakeResponse:
            # currentPage reported does not match requested
            return FakeResponse({
                "info": {"currentPage": 99, "nextPage": None},
                "results": [fake_gcc_row("c1")],
            })

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_file = root / "state.json"
            state_file.write_text(
                json.dumps({"schema_version": 1, "last_page": 2, "total_pages_seen": 68}),
                encoding="utf-8",
            )

            with self.assertRaises(rotation.RotationError):
                rotation.fetch_fixed_rotation_batch(
                    state_file,
                    root / "fixture.json",
                    root / "manifest.json",
                    pages_per_run=4,
                    http_get=fake_get_wrong_page,
                )

            current_state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(current_state["last_page"], 2)

    def test_failed_neon_ingest_does_not_advance_cursor(self):
        def fake_get(url: str, params: Mapping[str, Any] = None, **kwargs: Any) -> FakeResponse:
            page = params.get("page", 1) if params else 1
            return FakeResponse({
                "info": {"currentPage": page, "nextPage": page + 1},
                "results": [fake_gcc_row("c1")],
            })

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_file = root / "state.json"
            manifest_file = root / "manifest.json"
            fixture_file = root / "fixture.json"

            state_file.write_text(
                json.dumps({"schema_version": 1, "last_page": 4, "total_pages_seen": 68}),
                encoding="utf-8",
            )

            rotation.fetch_fixed_rotation_batch(
                state_file,
                fixture_file,
                manifest_file,
                pages_per_run=4,
                http_get=fake_get,
            )

            # Simulated failure: sidecar / Neon ingest failed, so commit is NOT called
            current_state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertEqual(current_state["last_page"], 4)

    def test_existing_sold_collector_and_pin_preserved(self):
        workflow_path = Path(".github/workflows/robot-kb-cloud-shadow.yml")
        content = workflow_path.read_text(encoding="utf-8")
        self.assertIn("1d06fe33b6fc640657255e15a8d17251aa02b6ce", content)
        self.assertIn("--live-gcc auction", content)
        self.assertIn("--live-gcc sold", content)

    def test_v4_economic_invariants_untouched(self):
        self.assertEqual(watcher.MAX_PRICE, 100)
        self.assertEqual(watcher.MIN_DISCOUNT, 30)
        self.assertEqual(watcher.MAX_AUCTION_MINUTES, 60)


if __name__ == "__main__":
    unittest.main()
