from __future__ import annotations

import importlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "mac" / "robot-kb-local"
if str(LOCAL) not in sys.path:
    sys.path.insert(0, str(LOCAL))

sold = importlib.import_module("robot_kb_magi_sold_marked")


class FakePage:
    def __init__(self):
        self.urls = []

    def goto(self, url, *args, **kwargs):
        self.urls.append(str(url))
        return "ok"

    def passthrough(self):
        return "delegated"


class RobotKbMagiSoldMarkedTests(unittest.TestCase):
    def snapshot(self):
        return sold.MagiSoldMarkedSnapshot(
            url="https://magi.camp/items/123",
            title="【PSA10】ピカチュウ 025/165 1枚",
            price_jpy=12000,
            observed_at=datetime(2026, 9, 7, 20, 0, tzinfo=timezone.utc),
            marker_reason="sold_listing",
        )

    def test_default_is_disabled_until_explicit_robot_kb_activation(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(sold.enabled())
        with patch.dict(os.environ, {"ROBOT_KB_MAGI_SOLD_MARKED_ENABLED": "true"}, clear=False):
            self.assertTrue(sold.enabled())

    def test_provider_presented_filter_is_search_only(self):
        search = "https://magi.camp/items/search?forms_search_items%5Bkeyword%5D=x"
        filtered = sold.presented_only_url(search)
        self.assertIn("forms_search_items%5Bstatus%5D=presented", filtered)
        self.assertEqual(filtered.count("forms_search_items%5Bstatus%5D=presented"), 1)
        self.assertEqual(
            sold.presented_only_url("https://magi.camp/items/123"),
            "https://magi.camp/items/123",
        )

    def test_page_proxy_only_rewrites_search_navigation(self):
        page = FakePage()
        proxy = sold.PresentedOnlyPage(page)
        proxy.goto("https://magi.camp/items/search?forms_search_items%5Bkeyword%5D=x")
        proxy.goto("https://magi.camp/items/123")
        self.assertIn("forms_search_items%5Bstatus%5D=presented", page.urls[0])
        self.assertEqual(page.urls[1], "https://magi.camp/items/123")
        self.assertEqual(proxy.passthrough(), "delegated")

    def test_only_single_psa10_cards_enter_history_lane(self):
        self.assertTrue(sold.eligible_single_card_title("【PSA10】ピカチュウ 025/165 1枚"))
        self.assertFalse(sold.eligible_single_card_title("【PSA9】ピカチュウ 025/165 1枚"))
        self.assertFalse(sold.eligible_single_card_title("【PSA10】ピカチュウ 025/165 2枚"))
        self.assertFalse(sold.eligible_single_card_title("【PSA10】ポケモンだいすきクラブ 087/080 1枚"))
        self.assertFalse(sold.eligible_single_card_title("【PSA10】ポケモンパルシティ 1枚"))
        self.assertFalse(sold.eligible_single_card_title("【PSA10】バトルロード サマー 2007 1枚"))

    def test_semantics_never_promote_marker_to_sale(self):
        snapshot = self.snapshot()
        semantic = sold.semantic_payload(snapshot)
        raw = sold.raw_payload(snapshot)
        self.assertEqual(semantic["snapshot_status"], "SOLD_MARKED")
        self.assertFalse(semantic["sale_evidence"])
        self.assertFalse(semantic["final_transaction_price_proven"])
        self.assertFalse(semantic["sale_date_proven"])
        self.assertNotIn("observed_at", semantic)
        self.assertIn("observed_at", raw)
        self.assertEqual(snapshot.stable_key, "magi_sold_marked:https://magi.camp/items/123")

    def test_disabled_harvest_performs_no_network_or_write(self):
        diag = SimpleNamespace(notes=[], source_failures=0)
        with patch.dict(os.environ, {}, clear=True):
            sold.harvest(
                object(),
                {"marketplace_fingerprints": {}},
                diag,
                now_fn=lambda: self.snapshot().observed_at,
                runtime=lambda: (_ for _ in ()).throw(AssertionError("runtime should not be used")),
                fingerprint_fn=lambda value: "fingerprint",
            )
        self.assertEqual(diag.notes, ["magi-sold-marked:disabled"])
        self.assertEqual(diag.source_failures, 0)


if __name__ == "__main__":
    unittest.main()
