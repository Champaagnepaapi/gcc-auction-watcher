from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import v4_auction_last_chance as last_chance
import watcher


class TestV4AuctionLastChance(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.final_alerts_path = Path(self.temp_dir.name) / "final_alerts.json"
        self.env_patcher = patch.dict("os.environ", {"V4_FAST_LANE_FINAL_CHECK_ENABLED": "true"})
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        self.temp_dir.cleanup()

    def test_armed_final_checks_filtering_due_only(self):
        # Auction A: notified 8 min ago with 12 min remaining -> 4 min remaining (DUE)
        notified_at_a = (self.now - timedelta(minutes=8)).isoformat()
        # Auction B: notified 2 min ago with 14 min remaining -> 12 min remaining (NOT DUE)
        notified_at_b = (self.now - timedelta(minutes=2)).isoformat()
        # Auction C: already sent final alert (IGNORED)
        notified_at_c = (self.now - timedelta(minutes=8)).isoformat()
        # Auction D: price exceeds max_recommended (IGNORED)
        notified_at_d = (self.now - timedelta(minutes=8)).isoformat()
        # Auction E: finished > 90s ago (STALE/EXPIRED)
        notified_at_e = (self.now - timedelta(minutes=15)).isoformat()

        state = {
            "notified": {
                "https://gcc.com/item/a": {
                    "price": 30.0,
                    "max_recommended": 50.0,
                    "minutes_to_end": 12.0,
                    "notified_at": notified_at_a,
                    "alert_15m_sent": True,
                    "final_alert_sent": False,
                },
                "https://gcc.com/item/b": {
                    "price": 20.0,
                    "max_recommended": 40.0,
                    "minutes_to_end": 14.0,
                    "notified_at": notified_at_b,
                    "alert_15m_sent": True,
                    "final_alert_sent": False,
                },
                "https://gcc.com/item/c": {
                    "price": 25.0,
                    "max_recommended": 45.0,
                    "minutes_to_end": 12.0,
                    "notified_at": notified_at_c,
                    "alert_15m_sent": True,
                    "final_alert_sent": True,
                },
                "https://gcc.com/item/d": {
                    "price": 60.0,
                    "max_recommended": 50.0,
                    "minutes_to_end": 12.0,
                    "notified_at": notified_at_d,
                    "alert_15m_sent": True,
                    "final_alert_sent": False,
                },
                "https://gcc.com/item/e": {
                    "price": 20.0,
                    "max_recommended": 50.0,
                    "minutes_to_end": 10.0,
                    "notified_at": notified_at_e,
                    "alert_15m_sent": True,
                    "final_alert_sent": False,
                },
            }
        }

        # With due_only=True (default), only A is returned
        due_armed = last_chance.armed_final_checks(state, self.now, due_only=True)
        self.assertEqual(len(due_armed), 1)
        self.assertEqual(due_armed[0].url, "https://gcc.com/item/a")
        self.assertEqual(due_armed[0].max_recommended, 50.0)
        self.assertAlmostEqual(due_armed[0].estimated_minutes_remaining, 4.0)

        # With due_only=False, both A and B are returned
        all_armed = last_chance.armed_final_checks(state, self.now, due_only=False)
        self.assertEqual(len(all_armed), 2)
        urls = {c.url for c in all_armed}
        self.assertEqual(urls, {"https://gcc.com/item/a", "https://gcc.com/item/b"})

    def test_requirement_a_fast_lane_at_t_minus_4_normal_watcher_at_t_minus_2_no_duplicate(self):
        """Requirement A: fast lane sends at T-4 -> normal watcher at T-2 does NOT duplicate."""
        notified_at = (self.now - timedelta(minutes=8)).isoformat()
        state = {
            "notified": {
                "https://gcc.com/item/pikachu": {
                    "price": 35.0,
                    "discount_pct": 65.0,
                    "max_recommended": 50.0,
                    "minutes_to_end": 12.0,
                    "notified_at": notified_at,
                    "alert_15m_sent": True,
                    "final_alert_sent": False,
                }
            }
        }

        fresh_lot = watcher.Lot(
            url="https://gcc.com/item/pikachu",
            title="Pikachu Illustrator PSA 9",
            current_price=35.0,
            source_type="auction",
            end_text="4 min",
            minutes_to_end=4,
        )

        mock_notify = MagicMock(return_value=True)

        # 1. Fast lane runs at T-4 and sends alert
        with patch("watcher.load_state", return_value=state):
            sent = last_chance.run_targeted_final_checks(
                now_fn=lambda: self.now,
                inspect_fn=lambda p, u: fresh_lot,
                notify_fn=mock_notify,
                final_alerts_file=self.final_alerts_path,
            )
        self.assertEqual(sent, 1)
        self.assertEqual(mock_notify.call_count, 1)

        # 2. Normal watcher runs at T-2 (2 minutes later) with fast-lane mode enabled
        lot_t2 = watcher.Lot(
            url="https://gcc.com/item/pikachu",
            title="Pikachu Illustrator PSA 9",
            current_price=35.0,
            source_type="auction",
            minutes_to_end=2,
        )
        mock_estimate = MagicMock()
        mock_estimate.adaptive_discount_pct = 0.30
        mock_estimate.grade_arbitrage = False
        op_t2 = watcher.Opportunity(
            lot=lot_t2,
            estimate=mock_estimate,
            discount_pct=65.0,
            max_recommended=50.0,
            gcc_comparables=[],
            ebay_comparables=[],
        )

        prev_in_state = state["notified"]["https://gcc.com/item/pikachu"]

        # Fast-lane guarded decision in normal watcher
        decision = last_chance.fast_lane_guarded_notification_decision(
            op_t2, prev_in_state, final_alerts_file=self.final_alerts_path, fast_lane_enabled=True
        )

        # PROOF: Normal watcher suppresses final_alert; NO duplicate notification!
        self.assertFalse(decision.final_alert)
        self.assertFalse(decision.should_notify)

    def test_requirement_b_normal_watcher_refreshes_item_to_4_min_fast_lane_checks_it(self):
        """Requirement B: normal watcher refreshes an armed item to 4 min -> fast lane can still check/send it."""
        notified_at = self.now.isoformat()
        state = {
            "notified": {
                "https://gcc.com/item/charizard": {
                    "price": 40.0,
                    "max_recommended": 70.0,
                    "minutes_to_end": 4.0,
                    "notified_at": notified_at,
                    "alert_15m_sent": True,
                    "final_alert_sent": False,
                }
            }
        }

        # Fast lane runs 1 minute later
        now_plus_1m = self.now + timedelta(minutes=1)

        fresh_lot = watcher.Lot(
            url="https://gcc.com/item/charizard",
            title="Charizard 1st Edition PSA 9",
            current_price=45.0,
            source_type="auction",
            end_text="3 min",
            minutes_to_end=3,
        )

        mock_notify = MagicMock(return_value=True)

        with patch("watcher.load_state", return_value=state):
            sent = last_chance.run_targeted_final_checks(
                now_fn=lambda: now_plus_1m,
                inspect_fn=lambda p, u: fresh_lot,
                notify_fn=mock_notify,
                final_alerts_file=self.final_alerts_path,
            )

        # PROOF: Fast lane correctly picks up and evaluates the item with stored 4 min countdown!
        self.assertEqual(sent, 1)
        self.assertEqual(mock_notify.call_count, 1)
        self.assertTrue(self.final_alerts_path.exists())

    def test_requirement_c_failed_ntfy_does_not_mark_sent_and_retries(self):
        """Requirement C: failed ntfy does NOT mark sent and next fast-lane run retries."""
        notified_at = (self.now - timedelta(minutes=8)).isoformat()
        state = {
            "notified": {
                "https://gcc.com/item/mew": {
                    "price": 30.0,
                    "max_recommended": 50.0,
                    "minutes_to_end": 12.0,
                    "notified_at": notified_at,
                    "alert_15m_sent": True,
                    "final_alert_sent": False,
                }
            }
        }

        fresh_lot = watcher.Lot(
            url="https://gcc.com/item/mew",
            title="Mew Gold Star PSA 9",
            current_price=35.0,
            source_type="auction",
            end_text="3 min",
            minutes_to_end=3,
        )

        # 1. First run: notify_fn fails (e.g. timeout / 500 error)
        mock_notify_fail = MagicMock(return_value=False)
        with patch("watcher.load_state", return_value=state):
            sent1 = last_chance.run_targeted_final_checks(
                now_fn=lambda: self.now,
                inspect_fn=lambda p, u: fresh_lot,
                notify_fn=mock_notify_fail,
                final_alerts_file=self.final_alerts_path,
            )
        self.assertEqual(sent1, 0)
        self.assertFalse(
            last_chance.is_final_alert_sent(
                "https://gcc.com/item/mew", state, last_chance.load_final_alerts(self.final_alerts_path)
            )
        )

        # 2. Next run (1 minute later): notify_fn succeeds
        mock_notify_success = MagicMock(return_value=True)
        with patch("watcher.load_state", return_value=state):
            sent2 = last_chance.run_targeted_final_checks(
                now_fn=lambda: self.now + timedelta(minutes=1),
                inspect_fn=lambda p, u: fresh_lot,
                notify_fn=mock_notify_success,
                final_alerts_file=self.final_alerts_path,
            )
        # PROOF: Retried successfully and now recorded!
        self.assertEqual(sent2, 1)
        self.assertTrue(
            last_chance.is_final_alert_sent(
                "https://gcc.com/item/mew", state, last_chance.load_final_alerts(self.final_alerts_path)
            )
        )

    def test_requirement_d_successful_alert_stays_exact_once_across_runs(self):
        """Requirement D: successful fast-lane alert stays exact-once across subsequent runs."""
        notified_at = (self.now - timedelta(minutes=8)).isoformat()
        state = {
            "notified": {
                "https://gcc.com/item/gengar": {
                    "price": 30.0,
                    "max_recommended": 50.0,
                    "minutes_to_end": 12.0,
                    "notified_at": notified_at,
                    "alert_15m_sent": True,
                    "final_alert_sent": False,
                }
            }
        }

        fresh_lot = watcher.Lot(
            url="https://gcc.com/item/gengar",
            title="Gengar Holo PSA 9",
            current_price=35.0,
            source_type="auction",
            end_text="3 min",
            minutes_to_end=3,
        )

        mock_notify = MagicMock(return_value=True)

        with patch("watcher.load_state", return_value=state):
            # Run 1: Sends alert
            sent1 = last_chance.run_targeted_final_checks(
                now_fn=lambda: self.now,
                inspect_fn=lambda p, u: fresh_lot,
                notify_fn=mock_notify,
                final_alerts_file=self.final_alerts_path,
            )
            self.assertEqual(sent1, 1)
            self.assertEqual(mock_notify.call_count, 1)

            # Run 2 (30s later): Exactly once, 0 duplicate alerts
            sent2 = last_chance.run_targeted_final_checks(
                now_fn=lambda: self.now + timedelta(seconds=30),
                inspect_fn=lambda p, u: fresh_lot,
                notify_fn=mock_notify,
                final_alerts_file=self.final_alerts_path,
            )
            self.assertEqual(sent2, 0)
            self.assertEqual(mock_notify.call_count, 1)

            # Run 3 (60s later): Still 0 duplicate alerts
            sent3 = last_chance.run_targeted_final_checks(
                now_fn=lambda: self.now + timedelta(seconds=60),
                inspect_fn=lambda p, u: fresh_lot,
                notify_fn=mock_notify,
                final_alerts_file=self.final_alerts_path,
            )
            self.assertEqual(sent3, 0)
            self.assertEqual(mock_notify.call_count, 1)

    def test_requirement_e_normal_watcher_and_fast_lane_cannot_overwrite_unrelated_state(self):
        """Requirement E: normal watcher and fast lane cannot overwrite each other's unrelated state."""
        notified_at = (self.now - timedelta(minutes=8)).isoformat()
        initial_state = {
            "seen": {"https://gcc.com/item/fixed_1": {"price": 10.0}},
            "fixed_economic_queue": {"items": {"item_123": {"active": True}}},
            "notified": {
                "https://gcc.com/item/auction_1": {
                    "price": 30.0,
                    "max_recommended": 50.0,
                    "minutes_to_end": 12.0,
                    "notified_at": notified_at,
                    "alert_15m_sent": True,
                    "final_alert_sent": False,
                }
            },
        }

        fresh_lot = watcher.Lot(
            url="https://gcc.com/item/auction_1",
            title="Lugia Holo PSA 9",
            current_price=35.0,
            source_type="auction",
            end_text="3 min",
            minutes_to_end=3,
        )

        mock_notify = MagicMock(return_value=True)

        with patch("watcher.load_state", return_value=copy.deepcopy(initial_state)), patch(
            "watcher.save_state"
        ) as mock_save_state:
            sent = last_chance.run_targeted_final_checks(
                now_fn=lambda: self.now,
                inspect_fn=lambda p, u: fresh_lot,
                notify_fn=mock_notify,
                final_alerts_file=self.final_alerts_path,
            )
            self.assertEqual(sent, 1)
            # PROOF: watcher.save_state is NEVER called by the fast lane!
            mock_save_state.assert_not_called()

        self.assertTrue(self.final_alerts_path.exists())
        saved_alerts = json.loads(self.final_alerts_path.read_text())
        self.assertIn("https://gcc.com/item/auction_1", saved_alerts)

    def test_run_targeted_final_checks_price_exceeded_fail_closed(self):
        notified_at = (self.now - timedelta(minutes=8)).isoformat()
        state = {
            "notified": {
                "https://gcc.com/item/test": {
                    "price": 30.0,
                    "max_recommended": 50.0,
                    "minutes_to_end": 12.0,
                    "notified_at": notified_at,
                    "alert_15m_sent": True,
                    "final_alert_sent": False,
                }
            }
        }

        # Price climbed to 55€ (> 50€ max_recommended)
        fresh_lot = watcher.Lot(
            url="https://gcc.com/item/test",
            title="Dracaufeu Holo PSA 9",
            current_price=55.0,
            source_type="auction",
            end_text="3 min",
            minutes_to_end=3,
        )

        mock_notify = MagicMock()
        with patch("watcher.load_state", return_value=state):
            sent = last_chance.run_targeted_final_checks(
                now_fn=lambda: self.now,
                inspect_fn=lambda p, u: fresh_lot,
                notify_fn=mock_notify,
                final_alerts_file=self.final_alerts_path,
            )

        self.assertEqual(sent, 0)
        mock_notify.assert_not_called()
        self.assertFalse(self.final_alerts_path.exists())

    def test_run_targeted_final_checks_unreadable_timer_fail_closed(self):
        notified_at = (self.now - timedelta(minutes=8)).isoformat()
        state = {
            "notified": {
                "https://gcc.com/item/test": {
                    "price": 30.0,
                    "max_recommended": 50.0,
                    "minutes_to_end": 12.0,
                    "notified_at": notified_at,
                    "alert_15m_sent": True,
                    "final_alert_sent": False,
                }
            }
        }

        fresh_lot = watcher.Lot(
            url="https://gcc.com/item/test",
            title="Dracaufeu Holo PSA 9",
            current_price=30.0,
            source_type="auction",
            end_text="",
            minutes_to_end=None,
        )

        mock_notify = MagicMock()
        with patch("watcher.load_state", return_value=state):
            sent = last_chance.run_targeted_final_checks(
                now_fn=lambda: self.now,
                inspect_fn=lambda p, u: fresh_lot,
                notify_fn=mock_notify,
                final_alerts_file=self.final_alerts_path,
            )

        self.assertEqual(sent, 0)
        mock_notify.assert_not_called()

    def test_env_missing_safe_off_default_zero_inspections(self):
        """Proof: When V4_FAST_LANE_FINAL_CHECK_ENABLED is absent, fast lane is safe-off (0 inspections, 0 ntfy, 0 state writes)."""
        state = {
            "notified": {
                "https://gcc.com/item/due_auction": {
                    "price": 30.0,
                    "max_recommended": 50.0,
                    "minutes_to_end": 12.0,
                    "notified_at": (self.now - timedelta(minutes=8)).isoformat(),
                    "alert_15m_sent": True,
                    "final_alert_sent": False,
                }
            }
        }
        mock_inspect = MagicMock()
        mock_notify = MagicMock()

        # Run with V4_FAST_LANE_FINAL_CHECK_ENABLED completely absent and no override
        with patch.dict("os.environ", {}, clear=True), patch("watcher.load_state", return_value=state) as mock_load_state:
            sent = last_chance.run_targeted_final_checks(
                now_fn=lambda: self.now,
                inspect_fn=mock_inspect,
                notify_fn=mock_notify,
                final_alerts_file=self.final_alerts_path,
            )

        self.assertEqual(sent, 0)
        mock_inspect.assert_not_called()
        mock_notify.assert_not_called()
        mock_load_state.assert_not_called()
        self.assertFalse(self.final_alerts_path.exists())

    def test_env_false_zero_inspections(self):
        """Proof: When V4_FAST_LANE_FINAL_CHECK_ENABLED=false, fast lane exits cleanly with 0 inspections/ntfy/writes."""
        state = {
            "notified": {
                "https://gcc.com/item/due_auction": {
                    "price": 30.0,
                    "max_recommended": 50.0,
                    "minutes_to_end": 12.0,
                    "notified_at": (self.now - timedelta(minutes=8)).isoformat(),
                    "alert_15m_sent": True,
                    "final_alert_sent": False,
                }
            }
        }
        mock_inspect = MagicMock()
        mock_notify = MagicMock()

        with patch.dict("os.environ", {"V4_FAST_LANE_FINAL_CHECK_ENABLED": "false"}), patch("watcher.load_state", return_value=state) as mock_load_state:
            sent = last_chance.run_targeted_final_checks(
                now_fn=lambda: self.now,
                inspect_fn=mock_inspect,
                notify_fn=mock_notify,
                final_alerts_file=self.final_alerts_path,
            )

        self.assertEqual(sent, 0)
        mock_inspect.assert_not_called()
        mock_notify.assert_not_called()
        mock_load_state.assert_not_called()
        self.assertFalse(self.final_alerts_path.exists())

    def test_env_true_execution_allowed(self):
        """Proof: When V4_FAST_LANE_FINAL_CHECK_ENABLED=true, fast lane runs inspection, sends ntfy, and persists alert."""
        state = {
            "notified": {
                "https://gcc.com/item/due_auction": {
                    "price": 30.0,
                    "max_recommended": 50.0,
                    "minutes_to_end": 12.0,
                    "notified_at": (self.now - timedelta(minutes=8)).isoformat(),
                    "alert_15m_sent": True,
                    "final_alert_sent": False,
                }
            }
        }
        fresh_lot = watcher.Lot(
            url="https://gcc.com/item/due_auction",
            title="Dracaufeu Holo PSA 9",
            current_price=35.0,
            source_type="auction",
            end_text="4 min",
            minutes_to_end=4.0,
        )
        mock_notify = MagicMock(return_value=True)

        with patch.dict("os.environ", {"V4_FAST_LANE_FINAL_CHECK_ENABLED": "true"}), patch("watcher.load_state", return_value=state):
            sent = last_chance.run_targeted_final_checks(
                now_fn=lambda: self.now,
                inspect_fn=lambda p, u: fresh_lot,
                notify_fn=mock_notify,
                final_alerts_file=self.final_alerts_path,
            )

        self.assertEqual(sent, 1)
        mock_notify.assert_called_once()
        self.assertTrue(self.final_alerts_path.exists())

    def test_explicit_override_true_and_false(self):
        """Proof: Explicit fast_lane_enabled argument correctly overrides environment in both directions."""
        state = {
            "notified": {
                "https://gcc.com/item/due_auction": {
                    "price": 30.0,
                    "max_recommended": 50.0,
                    "minutes_to_end": 12.0,
                    "notified_at": (self.now - timedelta(minutes=8)).isoformat(),
                    "alert_15m_sent": True,
                    "final_alert_sent": False,
                }
            }
        }
        fresh_lot = watcher.Lot(
            url="https://gcc.com/item/due_auction",
            title="Dracaufeu Holo PSA 9",
            current_price=35.0,
            source_type="auction",
            end_text="4 min",
            minutes_to_end=4.0,
        )
        mock_notify = MagicMock(return_value=True)

        # 1. Env is false, but fast_lane_enabled=True -> executes
        with patch.dict("os.environ", {"V4_FAST_LANE_FINAL_CHECK_ENABLED": "false"}), patch("watcher.load_state", return_value=state):
            sent = last_chance.run_targeted_final_checks(
                now_fn=lambda: self.now,
                inspect_fn=lambda p, u: fresh_lot,
                notify_fn=mock_notify,
                final_alerts_file=self.final_alerts_path,
                fast_lane_enabled=True,
            )
        self.assertEqual(sent, 1)

        # 2. Env is true, but fast_lane_enabled=False -> blocked
        mock_inspect2 = MagicMock()
        mock_notify2 = MagicMock()
        temp_alerts2 = Path(self.temp_dir.name) / "final_alerts2.json"
        with patch.dict("os.environ", {"V4_FAST_LANE_FINAL_CHECK_ENABLED": "true"}), patch("watcher.load_state", return_value=state):
            sent2 = last_chance.run_targeted_final_checks(
                now_fn=lambda: self.now,
                inspect_fn=mock_inspect2,
                notify_fn=mock_notify2,
                final_alerts_file=temp_alerts2,
                fast_lane_enabled=False,
            )
        self.assertEqual(sent2, 0)
        mock_inspect2.assert_not_called()
        mock_notify2.assert_not_called()
        self.assertFalse(temp_alerts2.exists())


if __name__ == "__main__":
    unittest.main()
