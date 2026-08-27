from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "mac" / "robot-kb-local"
if str(LOCAL) not in sys.path:
    sys.path.insert(0, str(LOCAL))

resilience = importlib.import_module("robot_kb_public_market_resilience")


@dataclass(frozen=True)
class Status:
    market: str
    status: str = "OK"
    pages: int = 1
    candidates: int = 0
    exact: int = 0
    detail: str = ""
    complete: bool = True


@dataclass(frozen=True)
class Capture:
    json_responses: int
    raw_listing_rows: int
    accepted_rows: int
    status: str = "OK"
    complete: bool = False


class FakePage:
    def __init__(self) -> None:
        self.waits: list[int] = []

    def wait_for_timeout(self, milliseconds: int) -> None:
        self.waits.append(milliseconds)


class RobotKbPublicMarketResilienceTests(unittest.TestCase):
    def test_fanatics_retries_one_transient_empty_source(self):
        page = FakePage()
        responses = [
            ([], Status("fanatics", candidates=0, exact=0, complete=True)),
            (["listing"], Status("fanatics", candidates=24, exact=3, detail="public browse", complete=True)),
        ]
        calls = []

        def original(_page, *args, **kwargs):
            calls.append((args, kwargs))
            return responses.pop(0)

        rows, status = resilience.fanatics_scan_with_retry(original, page, object(), observed_at=object())
        self.assertEqual(rows, ["listing"])
        self.assertEqual(status.candidates, 24)
        self.assertEqual(status.exact, 3)
        self.assertTrue(status.complete)
        self.assertIn("hydration retry recovered source", status.detail)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(page.waits), 1)

    def test_fanatics_zero_twice_is_fail_visible_not_complete(self):
        page = FakePage()
        calls = 0

        def original(_page, *args, **kwargs):
            nonlocal calls
            calls += 1
            return [], Status("fanatics", candidates=0, exact=0, detail="no routes", complete=True)

        rows, status = resilience.fanatics_scan_with_retry(original, page)
        self.assertEqual(rows, [])
        self.assertEqual(calls, 2)
        self.assertEqual(status.status, "RETRYABLE_EMPTY")
        self.assertFalse(status.complete)
        self.assertIn("after 2 bounded attempts", status.detail)
        self.assertEqual(resilience.count_fail_visible_statuses((status,)), 1)

    def test_identity_zero_with_source_candidates_does_not_retry(self):
        page = FakePage()
        calls = 0

        def original(_page, *args, **kwargs):
            nonlocal calls
            calls += 1
            return [], Status("fanatics", candidates=24, exact=0, detail="identity blocked", complete=True)

        _rows, status = resilience.fanatics_scan_with_retry(original, page)
        self.assertEqual(calls, 1)
        self.assertEqual(status.status, "OK")
        self.assertEqual(status.candidates, 24)
        self.assertEqual(status.exact, 0)
        self.assertEqual(page.waits, [])

    def test_comc_retries_one_transient_empty_source(self):
        page = FakePage()
        responses = [
            ([], Status("comc", candidates=0, exact=0, complete=True)),
            (["listing"], Status("comc", candidates=102, exact=8, complete=True)),
        ]

        def original(_page, *args, **kwargs):
            return responses.pop(0)

        rows, status = resilience.comc_scan_with_retry(original, page, object())
        self.assertEqual(rows, ["listing"])
        self.assertEqual(status.candidates, 102)
        self.assertEqual(status.exact, 8)
        self.assertTrue(status.complete)

    def test_cardova_retries_missing_public_json_with_longer_settle(self):
        page = FakePage()
        calls = []
        responses = [
            Capture(0, 0, 0, status="NO_PUBLIC_JSON"),
            Capture(24, 38, 17, status="OK"),
        ]

        def original(_page, *args, **kwargs):
            calls.append(dict(kwargs))
            return responses.pop(0)

        capture = resilience.cardova_capture_with_retry(original, page, max_pages_each=2, settle_ms=900)
        self.assertEqual(capture.status, "OK")
        self.assertEqual(capture.json_responses, 24)
        self.assertEqual(capture.raw_listing_rows, 38)
        self.assertEqual(capture.accepted_rows, 17)
        self.assertEqual(calls[1]["settle_ms"], 1500)
        self.assertFalse(capture.complete)

    def test_cardova_raw_rows_prove_retrieval_even_if_strict_scope_accepts_zero(self):
        page = FakePage()
        calls = 0

        def original(_page, *args, **kwargs):
            nonlocal calls
            calls += 1
            return Capture(5, 12, 0, status="OK")

        capture = resilience.cardova_capture_with_retry(original, page)
        self.assertEqual(calls, 1)
        self.assertEqual(capture.status, "OK")
        self.assertEqual(capture.accepted_rows, 0)
        self.assertEqual(page.waits, [])

    def test_cardova_zero_twice_remains_fail_visible(self):
        page = FakePage()

        def original(_page, *args, **kwargs):
            return Capture(0, 0, 0, status="NO_PUBLIC_JSON")

        capture = resilience.cardova_capture_with_retry(original, page)
        self.assertEqual(capture.status, "NO_PUBLIC_JSON")
        self.assertFalse(capture.complete)
        status = Status("cardova", status=capture.status, complete=False)
        self.assertEqual(resilience.count_fail_visible_statuses((status,)), 1)

    def test_market_details_are_bounded_and_visible(self):
        status = Status(
            "cardova",
            candidates=38,
            exact=17,
            detail="public anonymous GET-only capture; json=24; raw=38; scope=17",
            complete=False,
        )
        notes = resilience.scan_status_detail_notes((status,))
        self.assertEqual(len(notes), 1)
        self.assertIn("market-detail:cardova:OK:exact=17:candidates=38:complete=False", notes[0])
        self.assertIn("json=24", notes[0])

    def test_entrypoint_installs_resilience_without_v4_production_wiring(self):
        entrypoint = (LOCAL / "robot_kb_multisource_entrypoint.py").read_text(encoding="utf-8")
        harvester = (LOCAL / "robot_kb_multisource_harvest.py").read_text(encoding="utf-8")
        self.assertIn("public_resilience.install(harvest)", entrypoint)
        self.assertNotIn("robot_kb_public_market_resilience", harvester)


if __name__ == "__main__":
    unittest.main()
