from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import v4_kb_shadow_bridge as bridge
import watcher


class FakeResponse:
    status_code = 200
    headers = {}

    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")
        return None


def gcc_row(
    native_id: str,
    *,
    price_cents: int = 5000,
    selling_type: str = "FIXED_PRICE",
    status: str = "ON_SALE",
    end_time: str | None = None,
    sold_at: str | None = None,
    category: str = "Pokemon",
    item_type: str = "CARDS",
):
    row = {
        "id": native_id,
        "status": status,
        "sellingType": selling_type,
        "priceInCents": price_cents,
        "price": price_cents / 100.0,
        "item": {
            "id": f"item-{native_id}",
            "title": "Pikachu Base Set 58/102",
            "gradingCompany": "PSA",
            "grade": "9",
            "serialNumber": "12345678",
            "rectoImageKey": "front.jpg",
            "versoImageKey": "back.jpg",
            "collectible": {
                "category": category,
                "type": item_type,
                "language": "French",
                "yearOfDistribution": "1999",
                "extension": "Base Set",
                "set": "Base Set",
                "reference": "58/102",
            },
        },
    }
    if end_time is not None:
        row["endTime"] = end_time
    if sold_at is not None:
        row["soldAt"] = sold_at
    return row


class V4KbShadowBridgeTests(unittest.TestCase):
    def setUp(self):
        bridge._FIXED_ROWS.clear()
        bridge._AUCTION_ROWS.clear()

    def test_capture_wrapper_is_transparent_and_collects_fixed_rows(self):
        row = gcc_row("fixed-1")
        response = FakeResponse({"info": {}, "results": [row]})
        wrapper = bridge.CapturingGccHttpGet(lambda *a, **k: response)
        returned = wrapper(
            bridge.GCC_API_URL,
            params={"sellingTypes": "FIXED_PRICE", "page": 1},
        )
        self.assertIs(returned, response)
        self.assertIn("fixed-1", bridge._FIXED_ROWS)
        self.assertEqual(bridge._FIXED_ROWS["fixed-1"].payload["priceInCents"], 5000)

    def test_capture_failure_never_changes_real_response(self):
        class BrokenJsonResponse(FakeResponse):
            def json(self):
                raise ValueError("broken capture payload")

        response = BrokenJsonResponse({})
        wrapper = bridge.CapturingGccHttpGet(lambda *a, **k: response)
        returned = wrapper(
            bridge.GCC_API_URL,
            params={"sellingTypes": "FIXED_PRICE"},
        )
        self.assertIs(returned, response)
        self.assertFalse(bridge._FIXED_ROWS)

    def test_flush_keeps_only_v4_eligible_near_final_auctions(self):
        now = datetime.now(timezone.utc)
        observed = now.isoformat(timespec="microseconds").replace("+00:00", "Z")
        within = (now + timedelta(minutes=4)).isoformat().replace("+00:00", "Z")
        later = (now + timedelta(minutes=20)).isoformat().replace("+00:00", "Z")
        bridge._FIXED_ROWS["fixed-1"] = bridge.CapturedRow(gcc_row("fixed-1"), observed)
        bridge._AUCTION_ROWS["auction-good"] = bridge.CapturedRow(
            gcc_row("auction-good", selling_type="AUCTION", end_time=within), observed
        )
        bridge._AUCTION_ROWS["auction-late"] = bridge.CapturedRow(
            gcc_row("auction-late", selling_type="AUCTION", end_time=later), observed
        )
        bridge._AUCTION_ROWS["auction-not-card"] = bridge.CapturedRow(
            gcc_row(
                "auction-not-card",
                selling_type="AUCTION",
                end_time=within,
                item_type="SEALED_PRODUCT",
            ),
            observed,
        )
        with tempfile.TemporaryDirectory() as directory:
            spool = Path(directory) / "spool.json"
            with patch.dict(
                os.environ,
                {
                    "V4_KB_SHADOW_SPOOL_PATH": str(spool),
                    "V4_KB_AUCTION_NEAR_FINAL_MINUTES": "12",
                },
                clear=False,
            ):
                self.assertEqual(bridge.flush_capture_if_configured(), spool)
            payload = json.loads(spool.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["fixed_rows"]), 1)
        self.assertEqual(len(payload["auction_near_final_rows"]), 1)
        self.assertEqual(
            payload["auction_near_final_rows"][0]["payload"]["id"], "auction-good"
        )
        self.assertEqual(payload["auction_near_final_rows"][0]["bucket"], "LE5")

    def test_filter_keeps_fixed_baseline_then_only_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spool = root / "spool.json"
            state = root / "state.json"
            pending = root / "pending.json"
            manifest = root / "manifest.json"
            raw = gcc_row("fixed-1", price_cents=5000)
            spool.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "captured_at": "2026-08-14T18:00:00Z",
                        "fixed_rows": [
                            {"payload": raw, "retrieved_at": "2026-08-14T18:00:00Z"}
                        ],
                        "auction_near_final_rows": [],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                bridge.filter_spool(spool, state, pending, manifest, revisit_ended=False, harvest_recent_sold=False),
                1,
            )
            bridge.commit_manifest(state, manifest)
            self.assertEqual(
                bridge.filter_spool(spool, state, pending, manifest, revisit_ended=False, harvest_recent_sold=False),
                0,
            )
            raw["priceInCents"] = 4200
            spool_payload = json.loads(spool.read_text(encoding="utf-8"))
            spool_payload["fixed_rows"][0]["payload"] = raw
            spool.write_text(json.dumps(spool_payload), encoding="utf-8")
            self.assertEqual(
                bridge.filter_spool(spool, state, pending, manifest, revisit_ended=False, harvest_recent_sold=False),
                1,
            )

    def test_auction_same_price_is_saved_again_only_when_bucket_gets_closer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spool = root / "spool.json"
            state = root / "state.json"
            pending = root / "pending.json"
            manifest = root / "manifest.json"
            row = gcc_row("auction-1", selling_type="AUCTION")

            def write(bucket: str):
                spool.write_text(
                    json.dumps(
                        {
                            "schema_version": 2,
                            "captured_at": "2026-08-14T18:00:00Z",
                            "fixed_rows": [],
                            "auction_near_final_rows": [
                                {
                                    "payload": row,
                                    "retrieved_at": "2026-08-14T18:00:00Z",
                                    "minutes_to_end": 4 if bucket == "LE5" else 10,
                                    "bucket": bucket,
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )

            write("LE12")
            self.assertEqual(
                bridge.filter_spool(spool, state, pending, manifest, revisit_ended=False, harvest_recent_sold=False),
                1,
            )
            bridge.commit_manifest(state, manifest)
            self.assertEqual(
                bridge.filter_spool(spool, state, pending, manifest, revisit_ended=False, harvest_recent_sold=False),
                0,
            )
            write("LE5")
            self.assertEqual(
                bridge.filter_spool(spool, state, pending, manifest, revisit_ended=False, harvest_recent_sold=False),
                1,
            )

    def test_is_proven_gcc_sold_strictness(self):
        # 1. Valid explicit SOLD
        valid_sold = gcc_row(
            "sold-1",
            status="SOLD",
            price_cents=12000,
            sold_at="2026-08-14T16:50:00Z",
        )
        self.assertTrue(bridge.is_proven_gcc_sold(valid_sold))

        # 2. WAITING_FOR_PAYMENT is never a sale
        waiting = gcc_row(
            "wait-1",
            status="WAITING_FOR_PAYMENT",
            price_cents=12000,
            sold_at=None,
        )
        self.assertFalse(bridge.is_proven_gcc_sold(waiting))

        # 3. COMPLETED alone is never a sale
        completed = gcc_row(
            "comp-1",
            status="COMPLETED",
            price_cents=12000,
            sold_at="2026-08-14T16:50:00Z",
        )
        self.assertFalse(bridge.is_proven_gcc_sold(completed))

        # 4. Missing soldAt timestamp is not a sale
        no_date = gcc_row(
            "no-date",
            status="SOLD",
            price_cents=12000,
            sold_at=None,
        )
        self.assertFalse(bridge.is_proven_gcc_sold(no_date))

        # 5. Price <= 0 is not a sale
        zero_price = gcc_row(
            "zero-price",
            status="SOLD",
            price_cents=0,
            sold_at="2026-08-14T16:50:00Z",
        )
        zero_price["price"] = 0
        self.assertFalse(bridge.is_proven_gcc_sold(zero_price))

        # 6. Non-Pokemon category is rejected
        non_poke = gcc_row(
            "non-poke",
            status="SOLD",
            price_cents=12000,
            sold_at="2026-08-14T16:50:00Z",
            category="Magic: The Gathering",
        )
        self.assertFalse(bridge.is_proven_gcc_sold(non_poke))

    def test_revisit_ended_auctions_captures_proven_sales(self):
        past = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat().replace("+00:00", "Z")
        state = {
            "schema_version": 2,
            "fixed": {},
            "auction": {
                "auc-sold": {"fingerprint": "fp1", "bucket": "LE5", "end_time": past},
                "auc-unpaid": {"fingerprint": "fp2", "bucket": "LE5", "end_time": past},
            },
            "sold": {},
            "ended_revisited": {},
        }

        def fake_get(url, *args, **kwargs):
            if "auc-sold" in url:
                row = gcc_row("auc-sold", status="SOLD", price_cents=8500, sold_at="2026-08-14T17:00:00Z")
                return FakeResponse(row)
            elif "auc-unpaid" in url:
                row = gcc_row("auc-unpaid", status="WAITING_FOR_PAYMENT", price_cents=8500)
                return FakeResponse(row)
            return FakeResponse({}, status_code=404)

        sales, updates = bridge.revisit_ended_auctions_in_state(state, http_get=fake_get)
        self.assertEqual(len(sales), 1)
        self.assertEqual(sales[0]["id"], "auc-sold")
        self.assertIn("auc-sold", updates["sold"])
        self.assertEqual(updates["sold"]["auc-sold"]["sold_at"], "2026-08-14T17:00:00Z")
        self.assertEqual(updates["ended_revisited"]["auc-sold"]["status"], "SOLD")
        self.assertEqual(updates["ended_revisited"]["auc-unpaid"]["status"], "WAITING_FOR_PAYMENT")

    def test_fixed_rotation_progression_and_wrap(self):
        """Test fixed cursor 1-4 -> 5-8 progression and safe wrap at inventory end."""
        calls = []

        def fake_get(url, params=None, *args, **kwargs):
            params = params or {}
            page = params.get("page", 1)
            selling_type = params.get("sellingTypes")
            group = params.get("sellingTypeGroup")
            status = params.get("status")
            calls.append((selling_type or group or status, page))

            if selling_type == "FIXED_PRICE":
                # Simulate total 6 pages of inventory
                total_items = 600
                total_pages = 6
                results = [gcc_row(f"fixed-p{page}-item{i}") for i in range(10)]
                next_page = (page + 1) if page < total_pages else None
                return FakeResponse({
                    "info": {"currentPage": page, "nextPage": next_page, "counts": {"fixedPriceCount": total_items}},
                    "results": results,
                })
            elif group == "AUCTION":
                # Auction backup always starting at page 1
                return FakeResponse({
                    "info": {"currentPage": 1, "nextPage": 2},
                    "results": [gcc_row("auc-1", selling_type="AUCTION", end_time="2026-08-14T19:00:00Z")],
                })
            elif status == "SOLD":
                return FakeResponse({
                    "info": {"currentPage": 1},
                    "results": [gcc_row("sold-1", status="SOLD", price_cents=5000, sold_at="2026-08-14T18:00:00Z")],
                })
            return FakeResponse({})

        with tempfile.TemporaryDirectory() as directory:
            rot_state = Path(directory) / "rotation_state.json"
            rot_manifest = Path(directory) / "rotation_manifest.json"

            # Run 1: start at 1 -> pages 1, 2, 3, 4
            spool1, manifest1 = bridge.collect_fixed_rotation_batch(
                rot_state,
                page_size=100,
                pages_per_run=4,
                http_get=fake_get,
            )
            self.assertEqual(manifest1["start_page"], 1)
            self.assertEqual(manifest1["last_page"], 4)
            self.assertEqual(manifest1["total_pages_seen"], 6)

            # Commit run 1
            bridge._atomic_json(rot_manifest, manifest1)
            bridge.commit_rotation_state(rot_state, rot_manifest)

            # Run 2: starts at page 5 -> fetches 5, 6, wraps to 1, 2 -> last page 2
            calls.clear()
            spool2, manifest2 = bridge.collect_fixed_rotation_batch(
                rot_state,
                page_size=100,
                pages_per_run=4,
                http_get=fake_get,
            )
            self.assertEqual(manifest2["start_page"], 5)
            self.assertEqual(manifest2["last_page"], 2)
            fixed_calls = [page for kind, page in calls if kind == "FIXED_PRICE"]
            self.assertEqual(fixed_calls, [5, 6, 1, 2])

    def test_cursor_does_not_advance_on_failed_ingest(self):
        with tempfile.TemporaryDirectory() as directory:
            rot_state = Path(directory) / "rotation_state.json"
            rot_manifest = Path(directory) / "rotation_manifest.json"

            initial_state = {
                "schema_version": 1,
                "last_page": 4,
                "total_pages_seen": 68,
                "updated_at": "2026-08-14T12:00:00Z",
            }
            bridge._atomic_json(rot_state, initial_state)

            def fake_get(url, params=None, *args, **kwargs):
                return FakeResponse({
                    "info": {"currentPage": 5, "nextPage": 6, "counts": {"fixedPriceCount": 6800}},
                    "results": [gcc_row("fixed-p5-1")],
                })

            spool, manifest = bridge.collect_fixed_rotation_batch(
                rot_state,
                page_size=100,
                pages_per_run=4,
                http_get=fake_get,
            )
            self.assertEqual(manifest["start_page"], 5)
            self.assertEqual(manifest["last_page"], 8)

            # Do NOT call commit_rotation_state (simulating failed ingest step)
            persisted = json.loads(rot_state.read_text(encoding="utf-8"))
            self.assertEqual(persisted["last_page"], 4)

    def test_auctions_always_start_from_ending_soon_page_1(self):
        auction_pages_requested = []

        def fake_get(url, params=None, *args, **kwargs):
            params = params or {}
            group = params.get("sellingTypeGroup")
            sort = params.get("sortType")
            page = params.get("page")
            if group == "AUCTION":
                auction_pages_requested.append((sort, page))
            return FakeResponse({
                "info": {"currentPage": 1, "nextPage": 2},
                "results": [],
            })

        with tempfile.TemporaryDirectory() as directory:
            rot_state = Path(directory) / "rot_state.json"
            bridge.collect_fixed_rotation_batch(
                rot_state,
                page_size=100,
                pages_per_run=4,
                http_get=fake_get,
            )
            self.assertEqual(auction_pages_requested, [("ENDING_SOON", 1)])

    def test_duplicate_sale_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spool = root / "spool.json"
            state = root / "state.json"
            pending = root / "pending.json"
            manifest = root / "manifest.json"

            sold_row = gcc_row("sold-1", status="SOLD", price_cents=5000, sold_at="2026-08-14T18:00:00Z")
            spool_payload = {
                "schema_version": 2,
                "captured_at": "2026-08-14T18:05:00Z",
                "fixed_rows": [],
                "auction_near_final_rows": [],
                "sold_rows": [{"payload": sold_row, "retrieved_at": "2026-08-14T18:05:00Z"}],
            }
            bridge._atomic_json(spool, spool_payload)

            # First filter creates 1 pending sale
            count1 = bridge.filter_spool(spool, state, pending, manifest, revisit_ended=False, harvest_recent_sold=False)
            self.assertEqual(count1, 1)
            bridge.commit_manifest(state, manifest)

            # Replaying exact same spool yields 0 pending items (idempotent deduplication)
            count2 = bridge.filter_spool(spool, state, pending, manifest, revisit_ended=False, harvest_recent_sold=False)
            self.assertEqual(count2, 0)

    def test_no_v4_economic_caps_changed(self):
        """Verify hard economic constraints are strictly untouched."""
        self.assertEqual(watcher.MAX_PRICE, 100)
        self.assertEqual(watcher.MIN_DISCOUNT, 30)
        self.assertEqual(watcher.MAX_AUCTION_MINUTES, 60)


if __name__ == "__main__":
    unittest.main()
