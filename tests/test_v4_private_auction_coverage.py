from __future__ import annotations

import unittest
from unittest.mock import patch

import watcher
import v4_private_auction_coverage as private_coverage


class PrivateAuctionCoverageTests(unittest.TestCase):
    def lot(self, suffix: str) -> watcher.Lot:
        return watcher.Lot(
            url=f"https://gradedcardcenter.com/item/{suffix}",
            title=f"PSA 9 Pikachu {suffix}",
            current_price=50.0,
            source_type="auction",
            minutes_to_end=30,
        )

    def test_only_private_sale_pages_are_opened(self):
        opened = []

        def collect_sale(_page, sale, source_type, _diagnostics):
            opened.append((sale, source_type))
            return [self.lot(sale.rsplit("/", 1)[-1])]

        sales = [
            "https://gradedcardcenter.com/filtres/auction/private/private-a",
            "https://gradedcardcenter.com/filtres/auction/weekly/weekly-a",
            "https://gradedcardcenter.com/filtres/auction/event/event-a",
        ]
        with patch.object(
            private_coverage.item_discovery,
            "_ORIGINAL_COLLECT_LIVE_AUCTION_URLS",
            return_value=sales,
        ), patch.object(
            private_coverage.item_discovery,
            "_ORIGINAL_COLLECT_LOTS_FROM_LISTING",
            side_effect=collect_sale,
        ):
            result = private_coverage.discover_private_auction_lots(object())

        self.assertEqual(result.sales_seen, 3)
        self.assertEqual(result.private_sales_seen, 1)
        self.assertEqual(result.failures, 0)
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(opened[0][1], "auction")
        self.assertIn("/auction/private/", opened[0][0])

    def test_private_results_are_deduplicated_against_api_results(self):
        primary = [self.lot("same"), self.lot("api-only")]
        private = [self.lot("same"), self.lot("private-only")]
        merged, added = private_coverage._merge_by_url(primary, private)
        self.assertEqual(added, 1)
        self.assertEqual({lot.url for lot in merged}, {
            self.lot("same").url,
            self.lot("api-only").url,
            self.lot("private-only").url,
        })

    def test_private_page_failure_is_counted_without_dropping_other_sales(self):
        sales = [
            "https://gradedcardcenter.com/filtres/auction/private/bad",
            "https://gradedcardcenter.com/filtres/auction/private/good",
        ]

        def collect_sale(_page, sale, _source_type, _diagnostics):
            if sale.endswith("/bad"):
                raise RuntimeError("boom")
            return [self.lot("good")]

        with patch.object(
            private_coverage.item_discovery,
            "_ORIGINAL_COLLECT_LIVE_AUCTION_URLS",
            return_value=sales,
        ), patch.object(
            private_coverage.item_discovery,
            "_ORIGINAL_COLLECT_LOTS_FROM_LISTING",
            side_effect=collect_sale,
        ):
            result = private_coverage.discover_private_auction_lots(object())

        self.assertEqual(result.failures, 1)
        self.assertEqual(len(result.lots), 1)

    def test_temporary_diagnostic_horizon_is_restored(self):
        old = watcher.MAX_AUCTION_MINUTES
        with patch.object(
            private_coverage.item_discovery,
            "_ORIGINAL_COLLECT_LIVE_AUCTION_URLS",
            return_value=[],
        ):
            private_coverage.discover_private_auction_lots(
                object(), max_minutes=720
            )
        self.assertEqual(watcher.MAX_AUCTION_MINUTES, old)


if __name__ == "__main__":
    unittest.main()
