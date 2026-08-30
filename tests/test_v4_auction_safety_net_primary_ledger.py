from __future__ import annotations

import unittest
from unittest.mock import patch

import watcher
import v4_private_auction_coverage as private_coverage


class AuctionSafetyNetPrimaryLedgerTests(unittest.TestCase):
    def lot(self, suffix: str, *, minutes: int = 30) -> watcher.Lot:
        return watcher.Lot(
            url=f"https://gradedcardcenter.com/item/{suffix}",
            title=f"PSA 9 Pikachu {suffix}",
            current_price=50.0,
            source_type="auction",
            minutes_to_end=minutes,
        )

    def test_helper_suppresses_only_urls_already_observed_by_primary_api(self):
        seen = self.lot("api-seen")
        gap = self.lot("legacy-gap")
        kept, suppressed = private_coverage._suppress_primary_api_observed(
            [seen, gap],
            {seen.url},
        )
        self.assertEqual([lot.url for lot in kept], [gap.url])
        self.assertEqual(suppressed, 1)

    def test_primary_api_terminal_exclusion_is_not_reintroduced_by_safety_net(self):
        saved_collect = watcher.collect_lots_from_listing
        saved_installed = private_coverage._INSTALLED
        diagnostics = watcher.RunDiagnostics()
        api_seen = self.lot("api-seen", minutes=30)
        api_kept = self.lot("api-kept", minutes=25)
        legacy_gap = self.lot("legacy-gap", minutes=20)

        diagnostics.auction_coverage.listing_ids.add(api_seen.url)
        diagnostics.auction_coverage.record_terminal(
            api_seen.url,
            watcher.ACCOUNT_EXCLUDED_BY_RULES,
        )

        def primary_collect(
            _page,
            _url,
            _source_type,
            run_diagnostics=None,
            **_kwargs,
        ):
            setattr(
                run_diagnostics,
                "auction_discovery_mode",
                private_coverage.item_discovery.PRIMARY_MODE,
            )
            return [api_kept]

        supplemental = private_coverage.PrivateAuctionAugmentResult(
            lots=[api_seen, legacy_gap],
            sales_seen=2,
            private_sales_seen=1,
            weekly_sales_seen=1,
            failures=0,
        )

        try:
            private_coverage._INSTALLED = False
            watcher.collect_lots_from_listing = primary_collect
            with patch.object(
                private_coverage,
                "discover_private_auction_lots",
                return_value=supplemental,
            ):
                private_coverage.install_v4_private_auction_coverage()
                result = watcher.collect_lots_from_listing(
                    object(),
                    private_coverage.item_discovery.AUCTION_INDEX_URL,
                    "auction",
                    diagnostics,
                )

            self.assertEqual(
                {lot.url for lot in result},
                {api_kept.url, legacy_gap.url},
            )
            self.assertNotIn(api_seen.url, {lot.url for lot in result})
            self.assertEqual(
                diagnostics.auction_coverage.terminal_statuses[api_seen.url],
                watcher.ACCOUNT_EXCLUDED_BY_RULES,
            )
            self.assertEqual(diagnostics.auction_private_candidates_added, 1)
            self.assertEqual(
                diagnostics.auction_private_already_observed_suppressed,
                1,
            )
            self.assertEqual(diagnostics.auction_coverage.incomplete_reasons, [])
        finally:
            watcher.collect_lots_from_listing = saved_collect
            private_coverage._INSTALLED = saved_installed

    def test_full_legacy_fallback_is_not_filtered_by_primary_api_ledger_rule(self):
        saved_collect = watcher.collect_lots_from_listing
        saved_installed = private_coverage._INSTALLED
        diagnostics = watcher.RunDiagnostics()
        legacy_seen = self.lot("legacy-seen")
        diagnostics.auction_coverage.listing_ids.add(legacy_seen.url)

        def fallback_collect(
            _page,
            _url,
            _source_type,
            run_diagnostics=None,
            **_kwargs,
        ):
            setattr(
                run_diagnostics,
                "auction_discovery_mode",
                private_coverage.item_discovery.FALLBACK_MODE,
            )
            return []

        supplemental = private_coverage.PrivateAuctionAugmentResult(
            lots=[legacy_seen],
            sales_seen=1,
            private_sales_seen=1,
            weekly_sales_seen=0,
            failures=0,
        )

        try:
            private_coverage._INSTALLED = False
            watcher.collect_lots_from_listing = fallback_collect
            with patch.object(
                private_coverage,
                "discover_private_auction_lots",
                return_value=supplemental,
            ):
                private_coverage.install_v4_private_auction_coverage()
                result = watcher.collect_lots_from_listing(
                    object(),
                    private_coverage.item_discovery.AUCTION_INDEX_URL,
                    "auction",
                    diagnostics,
                )

            self.assertEqual([lot.url for lot in result], [legacy_seen.url])
            self.assertEqual(
                diagnostics.auction_private_already_observed_suppressed,
                0,
            )
        finally:
            watcher.collect_lots_from_listing = saved_collect
            private_coverage._INSTALLED = saved_installed


if __name__ == "__main__":
    unittest.main()
