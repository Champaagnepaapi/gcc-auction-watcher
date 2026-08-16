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

    def test_private_and_weekly_sale_pages_are_opened_but_event_is_not(self):
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
        self.assertEqual(result.weekly_sales_seen, 1)
        self.assertEqual(result.failures, 0)
        self.assertEqual(len(result.lots), 2)
        self.assertTrue(all(source_type == "auction" for _, source_type in opened))
        self.assertEqual(
            {sale for sale, _ in opened},
            {
                sales[0],
                sales[1],
            },
        )

    def test_private_and_weekly_results_are_deduplicated_against_api_results(self):
        primary = [self.lot("same"), self.lot("api-only")]
        supplemental = [self.lot("same"), self.lot("weekly-only")]
        merged, added = private_coverage._merge_by_url(primary, supplemental)
        self.assertEqual(added, 1)
        self.assertEqual({lot.url for lot in merged}, {
            self.lot("same").url,
            self.lot("api-only").url,
            self.lot("weekly-only").url,
        })

    def test_supplemental_page_failure_is_counted_without_dropping_other_sales(self):
        sales = [
            "https://gradedcardcenter.com/filtres/auction/weekly/bad",
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
        self.assertEqual(result.private_sales_seen, 1)
        self.assertEqual(result.weekly_sales_seen, 1)
        self.assertEqual(len(result.lots), 1)

    def test_supplemental_legacy_accounting_does_not_mutate_primary_api_ledger(self):
        primary = watcher.RunDiagnostics()
        primary.auction_coverage.expected_total = 14338
        primary.auction_coverage.expected_total_scope = watcher.EXPECTED_TOTAL_SAME_QUERY
        primary.auction_coverage.pages_requested = 5
        primary.auction_coverage.pages_successful = 5
        primary.auction_coverage.rows_received = 120

        def collect_sales(_page, diagnostics):
            diagnostics.auction_coverage.record_page_success(
                "legacy-home",
                ["weekly-sale"],
                expected_total=7,
                expected_total_scope=watcher.EXPECTED_TOTAL_DIFFERENT_SCOPE,
            )
            return ["https://gradedcardcenter.com/filtres/auction/weekly/weekly-sale"]

        def collect_sale(_page, _sale, _source_type, diagnostics):
            diagnostics.auction_coverage.record_page_success(
                "weekly-sale",
                ["weekly-card"],
                expected_total=1,
                expected_total_scope=watcher.EXPECTED_TOTAL_DIFFERENT_SCOPE,
            )
            return [self.lot("weekly-card")]

        with patch.object(
            private_coverage.item_discovery,
            "_ORIGINAL_COLLECT_LIVE_AUCTION_URLS",
            side_effect=collect_sales,
        ), patch.object(
            private_coverage.item_discovery,
            "_ORIGINAL_COLLECT_LOTS_FROM_LISTING",
            side_effect=collect_sale,
        ):
            result = private_coverage.discover_private_auction_lots(
                object(), run_diagnostics=primary
            )

        self.assertEqual(result.failures, 0)
        self.assertEqual(result.weekly_sales_seen, 1)
        self.assertEqual(primary.auction_coverage.expected_total, 14338)
        self.assertEqual(
            primary.auction_coverage.expected_total_scope,
            watcher.EXPECTED_TOTAL_SAME_QUERY,
        )
        self.assertEqual(primary.auction_coverage.pages_requested, 5)
        self.assertEqual(primary.auction_coverage.pages_successful, 5)
        self.assertEqual(primary.auction_coverage.rows_received, 120)
        self.assertNotIn(
            "conflicting expected_total scopes",
            primary.auction_coverage.incomplete_reasons,
        )

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
