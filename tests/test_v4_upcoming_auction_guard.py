from __future__ import annotations

from datetime import datetime, timezone
import unittest

import watcher
import v4_auction_item_discovery as auction_discovery
import v4_auction_pagination_stability as stability
import v4_upcoming_auction_guard as guard


NOW = datetime(2026, 8, 27, 18, 43, tzinfo=timezone.utc)


def auction_row(*, start_time=None, end_time="2026-08-27T19:30:00Z") -> dict:
    row = {
        "id": "d7da5f05-ec15-4044-9149-df3071869140",
        "status": "ON_SALE",
        "price": 10.0,
        "priceInCents": 1000,
        "sellingType": "AUCTION",
        "endTime": end_time,
        "item": {
            "title": "Poochyena",
            "gradingCompany": "PSA",
            "grade": "10",
            "collectible": {
                "category": "Pokemon",
                "language": "Japanese",
                "yearOfDistribution": "2022",
                "extension": "VSTAR Universe",
                "set": "VSTAR Universe",
                "reference": "208/172",
                "type": "CARDS",
            },
        },
    }
    if start_time is not None:
        row["startTime"] = start_time
    return row


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeGet:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def __call__(self, *_args, **_kwargs):
        self.calls += 1
        return FakeResponse(self.payload)


def payload(row: dict) -> dict:
    return {
        "info": {
            "currentPage": 1,
            "nextPage": None,
            "counts": {"total": 1, "auctionCount": 1, "fixedPriceCount": 0},
        },
        "results": [row],
    }


class UpcomingAuctionStructuredGuardTests(unittest.TestCase):
    def setUp(self):
        self.base_discover = guard._BASE_DISCOVER_AUCTION_API_LOTS
        guard._BASE_DISCOVER_AUCTION_API_LOTS = guard._DEFAULT_DISCOVER_AUCTION_API_LOTS

    def tearDown(self):
        guard._BASE_DISCOVER_AUCTION_API_LOTS = self.base_discover

    def test_future_start_is_explicitly_upcoming(self):
        row = auction_row(start_time="2026-08-27T19:00:00Z")
        self.assertTrue(guard.is_upcoming_auction_row(row, observed_at=NOW))

    def test_started_auction_is_not_upcoming(self):
        row = auction_row(start_time="2026-08-27T18:00:00Z")
        self.assertFalse(guard.is_upcoming_auction_row(row, observed_at=NOW))

    def test_missing_or_naive_start_time_is_not_guessed(self):
        self.assertFalse(guard.is_upcoming_auction_row(auction_row(), observed_at=NOW))
        self.assertFalse(
            guard.is_upcoming_auction_row(
                auction_row(start_time="2026-08-27T19:00:00"),
                observed_at=NOW,
            )
        )

    def test_future_start_row_never_becomes_price_or_countdown_candidate(self):
        getter = FakeGet(payload(auction_row(start_time="2026-08-27T19:00:00Z")))
        result = guard.guarded_discover_auction_api_lots(
            max_minutes=60,
            http_get=getter,
            now=NOW,
        )
        self.assertTrue(result.complete)
        self.assertEqual(result.lots, [])
        self.assertEqual(getattr(result.coverage, "auction_upcoming_excluded", 0), 1)
        self.assertEqual(getter.calls, 1)

    def test_started_row_keeps_normal_live_auction_semantics(self):
        getter = FakeGet(payload(auction_row(start_time="2026-08-27T18:00:00Z")))
        result = guard.guarded_discover_auction_api_lots(
            max_minutes=60,
            http_get=getter,
            now=NOW,
        )
        self.assertTrue(result.complete)
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].current_price, 10.0)
        self.assertEqual(result.lots[0].minutes_to_end, 47)
        self.assertEqual(getattr(result.coverage, "auction_upcoming_excluded", 0), 0)

    def test_malformed_row_without_stable_id_is_not_hidden(self):
        row = auction_row(start_time="2026-08-27T19:00:00Z")
        row.pop("id")
        getter = FakeGet(payload(row))
        result = guard.guarded_discover_auction_api_lots(
            max_minutes=60,
            http_get=getter,
            now=NOW,
        )
        self.assertEqual(getattr(result.coverage, "auction_upcoming_excluded", 0), 0)
        self.assertGreaterEqual(result.coverage.unkeyed_rows, 1)


class UpcomingAuctionRenderedGuardTests(unittest.TestCase):
    def test_action_marker_is_strong_upcoming_proof(self):
        body = "Enchères à venir\nDébut le jeudi 27.08.2026 à 21h00\n10€\nProgrammer une enchère"
        self.assertTrue(guard.rendered_page_proves_upcoming(body))

    def test_navigation_heading_alone_is_not_enough(self):
        self.assertFalse(
            guard.rendered_page_proves_upcoming(
                "Enchères à venir\nWeekly Auction\nFin le 27/08 à 21h00\nEnchérir"
            )
        )
        self.assertFalse(
            guard.rendered_page_proves_upcoming(
                "Upcoming Auctions\nCurrent auction\nBid now"
            )
        )

    def test_heading_plus_explicit_start_label_is_upcoming(self):
        self.assertTrue(
            guard.rendered_page_proves_upcoming(
                "Upcoming Auction\nAuction starts at 21:00\nStarting bid 10€"
            )
        )

    def test_rendered_upcoming_page_clears_starting_price_and_start_countdown(self):
        original = guard._BASE_INSPECT_ITEM

        def fake_inspect(_page, lot, *, log_listing_errors=True):
            lot.body = "Enchères à venir\n10€\nProgrammer une enchère"
            lot.current_price = 10.0
            lot.minutes_to_end = 16
            lot.end_text = "0j 0h 16m 0s"
            return lot

        guard._BASE_INSPECT_ITEM = fake_inspect
        try:
            lot = watcher.Lot(
                url="https://gradedcardcenter.com/item/d7da5f05-ec15-4044-9149-df3071869140",
                title="Poochyena",
                current_price=10.0,
                source_type="auction",
            )
            inspected = guard.guarded_inspect_item(object(), lot)
        finally:
            guard._BASE_INSPECT_ITEM = original

        self.assertIsNone(inspected.current_price)
        self.assertIsNone(inspected.minutes_to_end)
        self.assertEqual(inspected.end_text, "")
        self.assertEqual(getattr(inspected, "auction_state", ""), guard.UPCOMING_AUCTION)


class UpcomingAuctionInstallerTests(unittest.TestCase):
    def test_guard_wraps_whichever_collector_is_current_at_install_time(self):
        saved_discover = auction_discovery.discover_auction_api_lots
        saved_inspect = watcher.inspect_item
        saved_base_discover = guard._BASE_DISCOVER_AUCTION_API_LOTS
        saved_base_inspect = guard._BASE_INSPECT_ITEM
        saved_installed = guard._INSTALLED_V4

        def current_collector(**_kwargs):
            return None

        def current_inspect(*_args, **_kwargs):
            return None

        try:
            auction_discovery.discover_auction_api_lots = current_collector
            watcher.inspect_item = current_inspect
            guard._INSTALLED_V4 = False
            guard.install_v4_upcoming_auction_guard()
            self.assertIs(guard._BASE_DISCOVER_AUCTION_API_LOTS, current_collector)
            self.assertIs(guard._BASE_INSPECT_ITEM, current_inspect)
            self.assertIs(
                auction_discovery.discover_auction_api_lots,
                guard.guarded_discover_auction_api_lots,
            )
            self.assertIs(watcher.inspect_item, guard.guarded_inspect_item)
        finally:
            auction_discovery.discover_auction_api_lots = saved_discover
            watcher.inspect_item = saved_inspect
            guard._BASE_DISCOVER_AUCTION_API_LOTS = saved_base_discover
            guard._BASE_INSPECT_ITEM = saved_base_inspect
            guard._INSTALLED_V4 = saved_installed

    def test_stability_installer_places_upcoming_guard_above_current_hardening(self):
        saved_discover = auction_discovery.discover_auction_api_lots
        saved_original = stability._ORIGINAL_DISCOVER_AUCTION_API_LOTS
        saved_installed = stability._INSTALLED
        saved_hardening_installer = stability.install_v4_auction_coverage_hardening
        saved_guard_installer = guard.install_v4_upcoming_auction_guard
        observed = []

        def initial_collector(**_kwargs):
            return None

        def hardened_collector(**_kwargs):
            return None

        def fake_hardening_installer():
            auction_discovery.discover_auction_api_lots = hardened_collector

        def fake_guard_installer():
            observed.append(auction_discovery.discover_auction_api_lots)

        try:
            auction_discovery.discover_auction_api_lots = initial_collector
            stability._INSTALLED = False
            stability.install_v4_auction_coverage_hardening = fake_hardening_installer
            guard.install_v4_upcoming_auction_guard = fake_guard_installer
            stability.install_v4_auction_pagination_stability()
            self.assertIs(stability._ORIGINAL_DISCOVER_AUCTION_API_LOTS, hardened_collector)
            self.assertEqual(observed, [stability.discover_auction_api_lots_stable])
        finally:
            auction_discovery.discover_auction_api_lots = saved_discover
            stability._ORIGINAL_DISCOVER_AUCTION_API_LOTS = saved_original
            stability._INSTALLED = saved_installed
            stability.install_v4_auction_coverage_hardening = saved_hardening_installer
            guard.install_v4_upcoming_auction_guard = saved_guard_installer


if __name__ == "__main__":
    unittest.main()
