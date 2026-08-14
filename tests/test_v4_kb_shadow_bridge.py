from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import v4_kb_shadow_bridge as bridge


class FakeResponse:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


def gcc_row(
    native_id: str,
    *,
    price_cents: int = 5000,
    selling_type: str = "FIXED_PRICE",
    end_time: str | None = None,
    category: str = "Pokemon",
    item_type: str = "CARDS",
):
    row = {
        "id": native_id,
        "status": "ON_SALE",
        "sellingType": selling_type,
        "priceInCents": price_cents,
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
                        "schema_version": 1,
                        "captured_at": "2026-08-14T18:00:00Z",
                        "fixed_rows": [
                            {"payload": raw, "retrieved_at": "2026-08-14T18:00:00Z"}
                        ],
                        "auction_near_final_rows": [],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(bridge.filter_spool(spool, state, pending, manifest), 1)
            bridge.commit_manifest(state, manifest)
            self.assertEqual(bridge.filter_spool(spool, state, pending, manifest), 0)
            raw["priceInCents"] = 4200
            spool_payload = json.loads(spool.read_text(encoding="utf-8"))
            spool_payload["fixed_rows"][0]["payload"] = raw
            spool.write_text(json.dumps(spool_payload), encoding="utf-8")
            self.assertEqual(bridge.filter_spool(spool, state, pending, manifest), 1)

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
                            "schema_version": 1,
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
            self.assertEqual(bridge.filter_spool(spool, state, pending, manifest), 1)
            bridge.commit_manifest(state, manifest)
            self.assertEqual(bridge.filter_spool(spool, state, pending, manifest), 0)
            write("LE5")
            self.assertEqual(bridge.filter_spool(spool, state, pending, manifest), 1)

    def test_no_spool_configuration_is_noop(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(bridge.flush_capture_if_configured())


if __name__ == "__main__":
    unittest.main()
