from __future__ import annotations

from datetime import datetime, timezone
import unittest

import watcher
import v4_auction_item_discovery as auction_discovery
import v4_auction_pagination_stability as stability
import v4_upcoming_auction_guard as guard


NOW = datetime(2026, 9, 3, 19, 0, tzinfo=timezone.utc)


class UpcomingAuctionPaginationDefaultRegressionTests(unittest.TestCase):
    def setUp(self):
        self.base_discover = guard._BASE_DISCOVER_AUCTION_API_LOTS

    def tearDown(self):
        guard._BASE_DISCOVER_AUCTION_API_LOTS = self.base_discover

    @staticmethod
    def _complete_result():
        coverage = watcher.CoverageAudit("AUCTIONS", watcher.AUCTION_DISCOVERY_FILTERS)
        return auction_discovery.AuctionApiDiscoveryResult(
            [],
            coverage,
            True,
            auction_discovery.PRIMARY_SCOPE_STATUS,
            0,
            0,
            0,
            True,
            False,
            0,
            auction_discovery.PRIMARY_EXHAUSTED_REASON,
        )

    def test_unspecified_pagination_keeps_wrapped_stability_page_size(self):
        observed = {}

        def stable_like_base(
            *,
            max_minutes=None,
            http_get=None,
            page_size=stability.STABLE_AUCTION_API_PAGE_SIZE,
            max_pages=auction_discovery.AUCTION_API_MAX_PAGES,
            now=None,
        ):
            observed["page_size"] = page_size
            observed["max_pages"] = max_pages
            return self._complete_result()

        guard._BASE_DISCOVER_AUCTION_API_LOTS = stable_like_base

        result = guard.guarded_discover_auction_api_lots(
            max_minutes=60,
            now=NOW,
        )

        self.assertTrue(result.complete)
        self.assertEqual(
            observed["page_size"],
            stability.STABLE_AUCTION_API_PAGE_SIZE,
        )
        self.assertEqual(
            observed["max_pages"],
            auction_discovery.AUCTION_API_MAX_PAGES,
        )

    def test_explicit_pagination_overrides_still_pass_through(self):
        observed = {}

        def stable_like_base(
            *,
            max_minutes=None,
            http_get=None,
            page_size=stability.STABLE_AUCTION_API_PAGE_SIZE,
            max_pages=auction_discovery.AUCTION_API_MAX_PAGES,
            now=None,
        ):
            observed["page_size"] = page_size
            observed["max_pages"] = max_pages
            return self._complete_result()

        guard._BASE_DISCOVER_AUCTION_API_LOTS = stable_like_base

        result = guard.guarded_discover_auction_api_lots(
            max_minutes=60,
            page_size=48,
            max_pages=7,
            now=NOW,
        )

        self.assertTrue(result.complete)
        self.assertEqual(observed["page_size"], 48)
        self.assertEqual(observed["max_pages"], 7)


if __name__ == "__main__":
    unittest.main()
