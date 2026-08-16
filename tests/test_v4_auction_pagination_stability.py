from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

import watcher
import v4_auction_item_discovery as item_discovery
from v4_auction_pagination_stability import (
    STABLE_AUCTION_API_PAGE_SIZE,
    UNSTABLE_REASON,
    discover_auction_api_lots_stable,
)


class AuctionPaginationStabilityTests(unittest.TestCase):
    def _result(self, urls, *, complete=True, reason="ok"):
        coverage = watcher.CoverageAudit("AUCTIONS", watcher.AUCTION_DISCOVERY_FILTERS)
        coverage.protocol = item_discovery.PRIMARY_PROTOCOL
        if complete:
            setattr(coverage, "_auction_scope_complete", True)
            setattr(
                coverage,
                "auction_scope_status",
                item_discovery.PRIMARY_SCOPE_STATUS,
            )
        return item_discovery.AuctionApiDiscoveryResult(
            lots=[SimpleNamespace(url=url) for url in urls],
            coverage=coverage,
            complete=complete,
            scope_status=(
                item_discovery.PRIMARY_SCOPE_STATUS
                if complete
                else item_discovery.FALLBACK_SCOPE_STATUS
            ),
            rows_seen=len(urls),
            timers_parsed=len(urls),
            timerless_eligible=0,
            order_verified=complete,
            threshold_crossed=complete,
            api_total=100,
            reason=reason,
        )

    def test_second_snapshot_can_recover_row_skipped_by_live_page_shift(self):
        snapshots = [
            self._result(["https://gcc/item/a", "https://gcc/item/c"]),
            self._result(
                [
                    "https://gcc/item/a",
                    "https://gcc/item/b",
                    "https://gcc/item/c",
                ]
            ),
            self._result(
                [
                    "https://gcc/item/a",
                    "https://gcc/item/b",
                    "https://gcc/item/c",
                ]
            ),
        ]
        calls = []

        def fake_discover(**kwargs):
            calls.append(kwargs)
            return snapshots[len(calls) - 1]

        anchor = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
        result = discover_auction_api_lots_stable(
            max_minutes=720,
            now=anchor,
            discover_func=fake_discover,
        )

        self.assertTrue(result.complete)
        self.assertEqual(
            {lot.url for lot in result.lots},
            {
                "https://gcc/item/a",
                "https://gcc/item/b",
                "https://gcc/item/c",
            },
        )
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(call["now"] == anchor for call in calls))
        self.assertTrue(
            all(call["page_size"] == STABLE_AUCTION_API_PAGE_SIZE for call in calls)
        )

    def test_stable_second_snapshot_stops_after_two_passes(self):
        snapshots = [
            self._result(["https://gcc/item/a", "https://gcc/item/b"]),
            self._result(["https://gcc/item/a", "https://gcc/item/b"]),
        ]
        calls = 0

        def fake_discover(**kwargs):
            nonlocal calls
            result = snapshots[calls]
            calls += 1
            return result

        result = discover_auction_api_lots_stable(discover_func=fake_discover)
        self.assertTrue(result.complete)
        self.assertEqual(calls, 2)

    def test_unstable_growth_fails_closed_for_existing_legacy_fallback(self):
        snapshots = [
            self._result(["https://gcc/item/a"]),
            self._result(["https://gcc/item/a", "https://gcc/item/b"]),
            self._result(
                [
                    "https://gcc/item/a",
                    "https://gcc/item/b",
                    "https://gcc/item/c",
                ]
            ),
        ]
        calls = 0

        def fake_discover(**kwargs):
            nonlocal calls
            result = snapshots[calls]
            calls += 1
            return result

        result = discover_auction_api_lots_stable(discover_func=fake_discover)
        self.assertFalse(result.complete)
        self.assertEqual(result.lots, [])
        self.assertEqual(result.scope_status, item_discovery.FALLBACK_SCOPE_STATUS)
        self.assertEqual(result.reason, UNSTABLE_REASON)
        self.assertIn(UNSTABLE_REASON, result.coverage.incomplete_reasons)

    def test_underlying_incomplete_pass_is_returned_without_synthetic_success(self):
        expected = self._result([], complete=False, reason="provider failure")
        calls = 0

        def fake_discover(**kwargs):
            nonlocal calls
            calls += 1
            return expected

        result = discover_auction_api_lots_stable(discover_func=fake_discover)
        self.assertIs(result, expected)
        self.assertEqual(calls, 1)
        self.assertFalse(result.complete)


if __name__ == "__main__":
    unittest.main()
