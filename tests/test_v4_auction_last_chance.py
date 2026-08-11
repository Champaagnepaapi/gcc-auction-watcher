from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import watcher
import v4_auction_last_chance as last_chance


BASE_TIME = datetime(2026, 8, 12, 0, 0, tzinfo=timezone.utc)


def notified_entry(
    *,
    minutes=10,
    price=50.0,
    max_recommended=70.0,
    final=False,
    alert_15=True,
    notified_at=BASE_TIME,
):
    return {
        "discount_pct": 50.0,
        "price": price,
        "notified_at": notified_at.isoformat(),
        "minutes_to_end": minutes,
        "max_recommended": max_recommended,
        "adaptive_discount_pct": 30.0,
        "grade_arbitrage": False,
        "valuation_path": "EXTERNAL_RESCUE",
        "alert_15m_sent": alert_15,
        "final_alert_sent": final,
        "last_reasons": ["passage sous 15 minutes"],
    }


def fresh_lot(url="https://gradedcardcenter.com/item/test", *, price=55.0, minutes=4):
    return watcher.Lot(
        url=url,
        title="Lugia",
        current_price=price,
        source_type="auction",
        minutes_to_end=minutes,
        end_text=f"0j 0h {minutes}m 0s",
        grader="PSA",
        grade="10",
    )


class Clock:
    def __init__(self, current=BASE_TIME):
        self.current = current
        self.sleeps = []

    def now(self):
        return self.current

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.current += timedelta(seconds=seconds)


class ArmedFinalCheckTests(unittest.TestCase):
    def test_only_already_notified_under_max_auctions_between_5_and_15_are_armed(self):
        state = {
            "notified": {
                "https://gcc.test/good": notified_entry(minutes=10),
                "https://gcc.test/already-final": notified_entry(minutes=10, final=True),
                "https://gcc.test/no-15": notified_entry(minutes=10, alert_15=False),
                "https://gcc.test/inside-five": notified_entry(minutes=5),
                "https://gcc.test/too-early": notified_entry(minutes=16),
                "https://gcc.test/over-max": notified_entry(
                    minutes=10, price=75, max_recommended=70
                ),
                "https://gcc.test/fixed": {
                    "price": 20,
                    "max_recommended": 30,
                    "minutes_to_end": None,
                    "notified_at": BASE_TIME.isoformat(),
                    "alert_15m_sent": False,
                    "final_alert_sent": False,
                },
            }
        }
        armed = last_chance.armed_final_checks(state, BASE_TIME)
        self.assertEqual([item.url for item in armed], ["https://gcc.test/good"])
        self.assertEqual(
            armed[0].due_at,
            BASE_TIME + timedelta(minutes=6),
        )
        self.assertEqual(armed[0].max_recommended, 70.0)

    def test_stale_estimated_auction_is_not_armed(self):
        old = BASE_TIME - timedelta(minutes=20)
        state = {"notified": {"https://gcc.test/stale": notified_entry(
            minutes=10,
            notified_at=old,
        )}}
        self.assertEqual(last_chance.armed_final_checks(state, BASE_TIME), [])


class TargetedFinalCheckRunTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.state_file = Path(self.tempdir.name) / "state.json"
        self.url = "https://gradedcardcenter.com/item/test"

    def tearDown(self):
        self.tempdir.cleanup()

    def write_state(self, entry):
        self.state_file.write_text(
            json.dumps({"notified": {self.url: entry}, "seen": {}}),
            encoding="utf-8",
        )

    def read_entry(self):
        return json.loads(self.state_file.read_text(encoding="utf-8"))["notified"][
            self.url
        ]

    def test_waits_to_target_window_rechecks_one_exact_page_and_marks_final(self):
        self.write_state(notified_entry(minutes=10))
        clock = Clock()
        inspections = []
        notifications = []

        def inspect(_page, url):
            inspections.append(url)
            return fresh_lot(url, price=55, minutes=4)

        def notify(lot, max_recommended):
            notifications.append((lot.current_price, max_recommended))
            return True

        with patch.object(watcher, "STATE_FILE", self.state_file):
            sent = last_chance.run_targeted_final_checks(
                now_fn=clock.now,
                sleep_fn=clock.sleep,
                inspect_fn=inspect,
                notify_fn=notify,
            )

        self.assertEqual(sent, 1)
        self.assertEqual(inspections, [self.url])
        self.assertEqual(notifications, [(55, 70.0)])
        self.assertEqual(clock.sleeps, [360.0])
        saved = self.read_entry()
        self.assertTrue(saved["final_alert_sent"])
        self.assertEqual(saved["price"], 55)
        self.assertEqual(saved["minutes_to_end"], 4)
        self.assertEqual(saved["max_recommended"], 70.0)

    def test_price_above_existing_max_is_fail_closed(self):
        self.write_state(notified_entry(minutes=10))
        clock = Clock()
        notifier = Mock(return_value=True)

        with patch.object(watcher, "STATE_FILE", self.state_file):
            sent = last_chance.run_targeted_final_checks(
                now_fn=clock.now,
                sleep_fn=clock.sleep,
                inspect_fn=lambda _page, url: fresh_lot(url, price=71, minutes=4),
                notify_fn=notifier,
            )

        self.assertEqual(sent, 0)
        notifier.assert_not_called()
        self.assertFalse(self.read_entry()["final_alert_sent"])

    def test_timer_must_be_reconfirmed_inside_five_minutes(self):
        self.write_state(notified_entry(minutes=10))
        clock = Clock()
        notifier = Mock(return_value=True)

        with patch.object(watcher, "STATE_FILE", self.state_file):
            sent = last_chance.run_targeted_final_checks(
                now_fn=clock.now,
                sleep_fn=clock.sleep,
                inspect_fn=lambda _page, url: fresh_lot(url, price=55, minutes=6),
                notify_fn=notifier,
            )

        self.assertEqual(sent, 0)
        notifier.assert_not_called()
        self.assertFalse(self.read_entry()["final_alert_sent"])

    def test_failed_page_refresh_never_sends_or_marks_final(self):
        self.write_state(notified_entry(minutes=10))
        clock = Clock()
        notifier = Mock(return_value=True)
        failed = fresh_lot(self.url, price=55, minutes=4)
        failed.inspection_error = "Timeout"

        with patch.object(watcher, "STATE_FILE", self.state_file):
            sent = last_chance.run_targeted_final_checks(
                now_fn=clock.now,
                sleep_fn=clock.sleep,
                inspect_fn=lambda _page, _url: failed,
                notify_fn=notifier,
            )

        self.assertEqual(sent, 0)
        notifier.assert_not_called()
        self.assertFalse(self.read_entry()["final_alert_sent"])

    def test_ntfy_failure_does_not_mark_final_so_normal_scan_can_retry(self):
        self.write_state(notified_entry(minutes=10))
        clock = Clock()

        with patch.object(watcher, "STATE_FILE", self.state_file):
            sent = last_chance.run_targeted_final_checks(
                now_fn=clock.now,
                sleep_fn=clock.sleep,
                inspect_fn=lambda _page, url: fresh_lot(url, price=55, minutes=4),
                notify_fn=lambda _lot, _max: False,
            )

        self.assertEqual(sent, 0)
        self.assertFalse(self.read_entry()["final_alert_sent"])


class LastChanceNotificationTests(unittest.TestCase):
    def test_message_contains_current_price_and_exact_existing_ceiling(self):
        response = Mock()
        response.raise_for_status.return_value = None
        lot = fresh_lot(price=61.25, minutes=4)
        with (
            patch.object(watcher, "NTFY_TOPIC", "test-topic"),
            patch.object(requests, "post", return_value=response) as post,
        ):
            self.assertTrue(
                last_chance.send_final_last_chance_notification(lot, 70.0)
            )

        message = post.call_args.kwargs["data"].decode("utf-8")
        self.assertIn("Prix actuel : 61.25 €", message)
        self.assertIn("Prix max conseillé : 70.00 €", message)
        self.assertIn("Marge restante sous plafond : 8.75 €", message)
        self.assertIn(lot.url, message)


if __name__ == "__main__":
    unittest.main()
