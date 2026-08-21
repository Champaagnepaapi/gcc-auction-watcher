from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping

import v4_kb_fixed_hybrid as hybrid


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def row(
    native_id: str,
    *,
    language: str = "French",
    grader: str = "PSA",
    grade: str = "10",
    edition: str = "Unlimited",
) -> dict[str, Any]:
    return {
        "id": native_id,
        "status": "ON_SALE",
        "sellingType": "FIXED_PRICE",
        "priceInCents": 5000,
        "price": 50.0,
        "item": {
            "id": f"item-{native_id}",
            "title": f"Card {native_id}",
            "gradingCompany": grader,
            "grade": grade,
            "collectible": {
                "category": "Pokemon",
                "type": "CARDS",
                "language": language,
                "edition": edition,
            },
        },
    }


class FixedHybridTests(unittest.TestCase):
    def test_100_recent_200_rotation_100_targeted_and_commit_after_success(self):
        calls: list[dict[str, Any]] = []

        def fake_get(url: str, params: Mapping[str, Any] = None, **kwargs: Any) -> FakeResponse:
            p = dict(params or {})
            calls.append(p)
            page = int(p.get("page", 1))
            target_keys = [key for key in hybrid.TARGET_DIMENSIONS if key in p]
            if p.get("sortType") == "MOST_RECENT" and target_keys:
                rows = [row(f"target-{i}") for i in range(int(p["limit"]))]
                return FakeResponse({"info": {"currentPage": 1, "nextPage": None}, "results": rows})
            if p.get("sortType") == "MOST_RECENT":
                rows = [row(f"recent-{i}") for i in range(int(p["limit"]))]
                return FakeResponse({"info": {"currentPage": 1, "nextPage": 2}, "results": rows})
            rows = [row(f"rotation-{page}-{i}") for i in range(int(p["limit"]))]
            return FakeResponse(
                {
                    "info": {
                        "currentPage": page,
                        "nextPage": page + 1,
                        "counts": {"fixedPriceCount": 6800},
                    },
                    "results": rows,
                }
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rotation_state = root / "rotation_state.json"
            target_state = root / "target_state.json"
            fixture = root / "fixture.json"
            manifest = root / "hybrid_manifest.json"
            rotation_manifest = root / "rotation_manifest.json"

            result = hybrid.fetch_fixed_hybrid_batch(
                rotation_state,
                target_state,
                fixture,
                manifest,
                rotation_manifest,
                http_get=fake_get,
            )

            self.assertEqual(result["recent_records_fetched"], 100)
            self.assertEqual(result["rotation_records_fetched"], 200)
            self.assertEqual(result["targeted_unique_added"], 100)
            self.assertEqual(result["total_unique_records"], 400)
            self.assertEqual(result["rotation_start_page"], 1)
            self.assertEqual(result["rotation_last_page"], 2)
            self.assertEqual(result["target_queries_used"], 1)
            self.assertFalse(rotation_state.exists())
            self.assertFalse(target_state.exists())

            rotation_calls = [p for p in calls if "sortType" not in p]
            recent_calls = [
                p
                for p in calls
                if p.get("sortType") == "MOST_RECENT"
                and not any(key in p for key in hybrid.TARGET_DIMENSIONS)
            ]
            targeted_calls = [
                p
                for p in calls
                if any(key in p for key in hybrid.TARGET_DIMENSIONS)
            ]
            self.assertEqual([p["page"] for p in rotation_calls], [1, 2])
            self.assertEqual(len(recent_calls), 1)
            self.assertEqual(recent_calls[0]["limit"], 100)
            self.assertEqual(len(targeted_calls), 1)
            self.assertEqual(targeted_calls[0]["languages"], json.dumps(["French"]))
            for p in recent_calls + targeted_calls:
                self.assertEqual(p["sellingTypes"], "FIXED_PRICE")
                self.assertEqual(p["categories"], "Pokemon")
                self.assertEqual(p["itemTypes"], "CARDS")
                self.assertEqual(p["status"], "ON_SALE")

            committed = hybrid.commit_fixed_hybrid_state(
                rotation_state,
                target_state,
                manifest,
                rotation_manifest,
            )
            self.assertEqual(committed["rotation"]["last_page"], 2)
            self.assertTrue(target_state.exists())

    def test_deduplicates_overlap_and_target_is_a_cap_not_a_quota(self):
        target_call_count = 0

        def fake_get(url: str, params: Mapping[str, Any] = None, **kwargs: Any) -> FakeResponse:
            nonlocal target_call_count
            p = dict(params or {})
            page = int(p.get("page", 1))
            if any(key in p for key in hybrid.TARGET_DIMENSIONS):
                target_call_count += 1
                return FakeResponse(
                    {
                        "info": {"currentPage": 1, "nextPage": None},
                        "results": [row("dup"), row("target-only")],
                    }
                )
            if p.get("sortType") == "MOST_RECENT":
                return FakeResponse(
                    {
                        "info": {"currentPage": 1, "nextPage": None},
                        "results": [row("dup"), row("recent-only")],
                    }
                )
            rotation_rows = [row("dup"), row(f"rotation-{page}")]
            return FakeResponse(
                {
                    "info": {
                        "currentPage": page,
                        "nextPage": page + 1,
                        "counts": {"fixedPriceCount": 12},
                    },
                    "results": rotation_rows,
                }
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = hybrid.fetch_fixed_hybrid_batch(
                root / "rotation.json",
                root / "target.json",
                root / "fixture.json",
                root / "manifest.json",
                root / "rotation_manifest.json",
                recent_records=2,
                rotation_pages=2,
                target_records=2,
                page_size=3,
                http_get=fake_get,
            )
            fixture_rows = json.loads((root / "fixture.json").read_text(encoding="utf-8"))
            ids = [r["id"] for r in fixture_rows]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(result["targeted_unique_added"], 1)
            self.assertLessEqual(result["targeted_unique_added"], 2)
            self.assertLessEqual(target_call_count, hybrid.MAX_TARGET_QUERIES)

    def test_fetch_failure_never_advances_rotation_or_target_state(self):
        def fake_get(url: str, params: Mapping[str, Any] = None, **kwargs: Any) -> FakeResponse:
            p = dict(params or {})
            page = int(p.get("page", 1))
            if p.get("sortType") == "MOST_RECENT":
                return FakeResponse({}, status_code=502)
            return FakeResponse(
                {
                    "info": {
                        "currentPage": page,
                        "nextPage": page + 1,
                        "counts": {"fixedPriceCount": 6800},
                    },
                    "results": [row(f"rotation-{page}")],
                }
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rotation_state = root / "rotation.json"
            target_state = root / "target.json"
            rotation_state.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "last_page": 4,
                        "total_pages_seen": 68,
                        "updated_at": "2026-08-15T10:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            initial = rotation_state.read_text(encoding="utf-8")

            with self.assertRaises(hybrid.HybridFixedError):
                hybrid.fetch_fixed_hybrid_batch(
                    rotation_state,
                    target_state,
                    root / "fixture.json",
                    root / "manifest.json",
                    root / "rotation_manifest.json",
                    http_get=fake_get,
                )

            self.assertEqual(rotation_state.read_text(encoding="utf-8"), initial)
            self.assertFalse(target_state.exists())

    def test_local_runner_wires_hybrid_fixed_and_preserves_auction_sold_split(self):
        runner = Path("mac/robot-kb-local/robot_kb_local_runner.sh").read_text(encoding="utf-8")
        installer = Path("mac/robot-kb-local/Installer Robot KB Local.command").read_text(encoding="utf-8")
        fixed_start = runner.index("run_fixed()")
        sold_start = runner.index("run_sold()")
        fixed = runner[fixed_start:sold_start]
        self.assertIn('write("com.robotpokemon.kb.fixed", "fixed", {"Minute": 32})', installer)
        self.assertIn('write("com.robotpokemon.kb.sold", "sold", [{"Minute": 17}, {"Minute": 47}])', installer)
        self.assertIn("--recent-records 100", fixed)
        self.assertIn("--rotation-pages 2", fixed)
        self.assertIn("--target-records 100", fixed)
        self.assertIn('v4_kb_fixed_hybrid.py" fetch', fixed)
        self.assertIn('v4_kb_fixed_hybrid.py" commit', fixed)
        self.assertIn("--live-gcc auction", fixed)
        self.assertNotIn("--live-gcc sold", fixed)
        self.assertIn("1d06fe33b6fc640657255e15a8d17251aa02b6ce", installer)


if __name__ == "__main__":
    unittest.main()
