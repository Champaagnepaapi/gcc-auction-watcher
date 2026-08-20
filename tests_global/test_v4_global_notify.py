from __future__ import annotations

import argparse
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import v4_global_notify as notify
from v4_global_market_core import ACTIVE_AUCTION, FIXED_ASK


def _card(price: float = 60.0) -> dict:
    url = "https://market.example/card-1"
    return {
        "identity": {
            "name": "Mewtwo",
            "set_name": "151",
            "number": "183/165",
            "language": "ja",
            "grader": "PSA",
            "grade": "10",
            "edition": "Unlimited",
            "finish": "",
            "variant": "Art Rare",
        },
        "fair_value_eur": 100.0,
        "offers": [
            {
                "market": "fanatics",
                "evidence_type": FIXED_ASK,
                "source_url": url,
                "all_in_eur": price,
            }
        ],
        "economic_confirmation": {
            "decision": {
                "status": "MULTIMARKET_CONFIRMED",
                "would_notify": True,
                "best_market": "fanatics",
                "source_url": url,
                "offer_all_in_eur": price,
                "gcc_fair_eur": 100.0,
                "external_fair_eur": 98.0,
                "confirmed_fair_eur": 98.0,
                "discount_pct": round((98.0 - price) / 98.0 * 100.0, 1),
                "external_provider": "PokemonPriceTracker",
                "external_sales_count": 20,
                "ask_is_sold": False,
            }
        },
    }


def _report(price: float = 60.0) -> dict:
    return {
        "schema_version": 3,
        "observed_at": "2026-08-20T09:00:00+00:00",
        "mode": "READ_ONLY_ECONOMIC_CONFIRMATION",
        "notifications": False,
        "transactions": False,
        "economic_confirmation": {
            "notification_capable": False,
            "activation_requires_separate_validation": True,
        },
        "cards": [_card(price)],
    }


class GlobalNotifyTests(unittest.TestCase):
    def _args(self, root: Path) -> argparse.Namespace:
        return argparse.Namespace(
            state=str(root / "state.json"),
            output_dir=str(root / "out"),
        )

    def test_candidate_requires_exact_actionable_offer(self):
        report = _report()
        self.assertEqual(len(notify.confirmed_notification_candidates(report)), 1)
        bad = copy.deepcopy(report)
        bad["cards"][0]["offers"][0]["evidence_type"] = ACTIVE_AUCTION
        self.assertEqual(notify.confirmed_notification_candidates(bad), [])

    def test_default_off_never_posts_and_reports_would_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(notify.confirmed, "run", return_value=_report()), patch.object(
                notify.requests, "post"
            ) as post, patch.dict(
                os.environ,
                {"GLOBAL_NOTIFY_ENABLED": "false", "NTFY_TOPIC": ""},
                clear=False,
            ):
                result = notify.run(self._args(root))
            post.assert_not_called()
            self.assertEqual(result["mode"], "READ_ONLY_NOTIFICATION_VALIDATION")
            self.assertFalse(result["notification_delivery"]["enabled"])
            self.assertEqual(result["notification_delivery"]["would_send_after_dedupe"], 1)
            self.assertEqual(result["notification_delivery"]["sent"], 0)
            self.assertFalse(result["transactions"])

    def test_enabled_without_topic_fails_before_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(notify.confirmed, "run") as run, patch.dict(
                os.environ,
                {"GLOBAL_NOTIFY_ENABLED": "true", "NTFY_TOPIC": ""},
                clear=False,
            ):
                with self.assertRaisesRegex(RuntimeError, "GLOBAL_NOTIFY_ENABLED_WITHOUT_TOPIC"):
                    notify.run(self._args(root))
            run.assert_not_called()

    def test_first_delivery_persists_then_same_listing_is_deduped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            response = Mock()
            response.raise_for_status.return_value = None
            env = {
                "GLOBAL_NOTIFY_ENABLED": "true",
                "NTFY_TOPIC": "unit-test-topic",
                "NTFY_SERVER": "https://ntfy.invalid",
            }
            with patch.object(notify.confirmed, "run", side_effect=[_report(), _report()]), patch.object(
                notify.requests, "post", return_value=response
            ) as post, patch.dict(os.environ, env, clear=False):
                first = notify.run(self._args(root))
                second = notify.run(self._args(root))
            self.assertEqual(post.call_count, 1)
            self.assertEqual(first["notification_delivery"]["sent"], 1)
            self.assertEqual(second["notification_delivery"]["sent"], 0)
            self.assertEqual(second["notification_delivery"]["deduped"], 1)
            state = json.loads((root / "state.json").read_text())
            self.assertEqual(len(state["notified"]), 1)

    def test_five_percent_price_improvement_realerts_inside_ttl(self):
        now = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
        previous = {
            "notified_at": (now - timedelta(hours=1)).isoformat(),
            "offer_all_in_eur": 100.0,
        }
        yes, reason = notify._should_deliver(
            previous,
            current_price=95.0,
            now=now,
            ttl_days=14,
            reprice_drop_pct=5.0,
        )
        self.assertTrue(yes)
        self.assertEqual(reason, "PRICE_IMPROVED")
        no, reason = notify._should_deliver(
            previous,
            current_price=96.0,
            now=now,
            ttl_days=14,
            reprice_drop_pct=5.0,
        )
        self.assertFalse(no)
        self.assertEqual(reason, "DEDUPED")

    def test_expired_ttl_can_realert(self):
        now = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
        previous = {
            "notified_at": (now - timedelta(days=15)).isoformat(),
            "offer_all_in_eur": 60.0,
        }
        yes, reason = notify._should_deliver(
            previous,
            current_price=60.0,
            now=now,
            ttl_days=14,
            reprice_drop_pct=5.0,
        )
        self.assertTrue(yes)
        self.assertEqual(reason, "TTL_EXPIRED")

    def test_malformed_state_fails_closed_when_notifications_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text('{"schema_version": 1, "cursor": 0, "notified": {"x": {}}}')
            with self.assertRaisesRegex(RuntimeError, "GLOBAL_NOTIFY_STATE_INVALID"):
                notify.load_state(path, strict=True)

    def test_notification_message_never_calls_ask_a_sale(self):
        card = _card()
        decision = card["economic_confirmation"]["decision"]
        title, body = notify._format_notification(card, decision, card["offers"][0])
        self.assertIn("GLOBAL EDGE CONFIRMÉ", title)
        self.assertIn("PAS UNE VENTE", body)
        self.assertIn("Vérification manuelle uniquement", body)

    def test_rotation_wraps_without_repeating_same_top_slice(self):
        tracker = {}
        original = notify.base.build_seed_panel
        notify.base.build_seed_panel = lambda sales, observed_at, max_identities: ["a", "b", "c", "d"]
        try:
            builder = notify._rotating_seed_builder(2, tracker)
            selected = builder([1, 2, 3, 4], observed_at=datetime.now(timezone.utc), max_identities=3)
        finally:
            notify.base.build_seed_panel = original
        self.assertEqual(selected, ["c", "d", "a"])
        self.assertEqual(tracker["next"], 1)
        self.assertEqual(tracker["total"], 4)


if __name__ == "__main__":
    unittest.main()
