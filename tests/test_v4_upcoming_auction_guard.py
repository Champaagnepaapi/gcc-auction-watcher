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


class FakeBodyLocator:
    def __init__(self, body):
        self.body = body

    def inner_text(self, timeout=None):
        return self.body


class FakePage:
    def __init__(self, body="", *, fail=False):
        self.body = body
        self.fail = fail
        self.goto_calls = []

    def goto(self, url, **_kwargs):
        self.goto_calls.append(url)
        if self.fail:
            raise RuntimeError("navigation failed")

    def wait_for_timeout(self, _milliseconds):
        return None

    def locator(self, selector):
        if selector != "body":
            raise AssertionError(f"unexpected selector {selector}")
        return FakeBodyLocator(self.body)


def auction_lot(
    *,
    url="https://gradedcardcenter.com/item/7a84f68f-80e6-42e2-8e46-52acf1de2d74",
    minutes=46,
) -> watcher.Lot:
    return watcher.Lot(
        url=url,
        title="Braixen",
        current_price=10.0,
        source_type="auction",
        minutes_to_end=minutes,
        end_text="0j 0h 46m 0s",
    )


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
        self.assertEqual(
            getattr(result.lots[0], "auction_start_state", ""),
            guard.STARTED_STRUCTURED,
        )
        self.assertEqual(getattr(result.coverage, "auction_upcoming_excluded", 0), 0)

    def test_missing_start_is_marked_unproven_for_rendered_verification(self):
        getter = FakeGet(payload(auction_row()))
        result = guard.guarded_discover_auction_api_lots(
            max_minutes=60,
            http_get=getter,
            now=NOW,
        )
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(
            getattr(result.lots[0], "auction_start_state", ""),
            guard.START_UNPROVEN,
        )

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

    def test_live_requires_bid_action_and_end_semantics(self):
        self.assertTrue(
            guard.rendered_page_proves_live(
                "Weekly Auction\n10€\n0 enchères\nFin le 06/09 @ 14h27\nEnchérir"
            )
        )
        self.assertFalse(
            guard.rendered_page_proves_live(
                "Weekly Auction\n10€\n0 enchères\nDébut le 06/09 @ 14h27\nProgrammer une enchère"
            )
        )
        self.assertFalse(
            guard.rendered_page_proves_live("Weekly Auction\n10€\n0 enchères")
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


class UpcomingAuctionMainLoopBypassRegressionTests(unittest.TestCase):
    def setUp(self):
        self.base_collect = guard._BASE_COLLECT_LOTS_FROM_LISTING

    def tearDown(self):
        guard._BASE_COLLECT_LOTS_FROM_LISTING = self.base_collect

    def _set_collector(self, lots):
        def fake_collect(*_args, **_kwargs):
            return list(lots)
        guard._BASE_COLLECT_LOTS_FROM_LISTING = fake_collect

    def test_timer_bearing_upcoming_api_lot_is_filtered_before_main_economics(self):
        lot = auction_lot()
        setattr(lot, "auction_start_state", guard.START_UNPROVEN)
        self._set_collector([lot])
        page = FakePage(
            "Enchères à venir\nDébut le 03/09 à 21h00\n10€\nProgrammer une enchère"
        )

        result = guard.guarded_collect_lots_from_listing(
            page,
            auction_discovery.AUCTION_INDEX_URL,
            "auction",
        )

        self.assertEqual(result, [])
        self.assertEqual(page.goto_calls, [lot.url])
        self.assertIsNone(lot.current_price)
        self.assertIsNone(lot.minutes_to_end)
        self.assertEqual(getattr(lot, "auction_state", ""), guard.UPCOMING_AUCTION)

    def test_timer_bearing_live_api_lot_is_retained_unchanged(self):
        lot = auction_lot()
        setattr(lot, "auction_start_state", guard.START_UNPROVEN)
        self._set_collector([lot])
        page = FakePage(
            "Weekly Auction\n10€\n0 enchères\nFin le 06/09 @ 14h27\nEnchérir"
        )

        result = guard.guarded_collect_lots_from_listing(
            page,
            auction_discovery.AUCTION_INDEX_URL,
            "auction",
        )

        self.assertEqual(result, [lot])
        self.assertEqual(lot.current_price, 10.0)
        self.assertEqual(lot.minutes_to_end, 46)
        self.assertEqual(getattr(lot, "auction_state", ""), guard.LIVE_AUCTION)

    def test_timer_bearing_ambiguous_page_fails_closed(self):
        lot = auction_lot()
        setattr(lot, "auction_start_state", guard.START_UNPROVEN)
        self._set_collector([lot])
        page = FakePage("Weekly Auction\n10€\n0 enchères")

        result = guard.guarded_collect_lots_from_listing(
            page,
            auction_discovery.AUCTION_INDEX_URL,
            "auction",
        )

        self.assertEqual(result, [])
        self.assertEqual(getattr(lot, "auction_state", ""), guard.START_UNPROVEN)

    def test_rendered_verification_error_fails_closed(self):
        lot = auction_lot()
        setattr(lot, "auction_start_state", guard.START_UNPROVEN)
        self._set_collector([lot])
        page = FakePage(fail=True)

        result = guard.guarded_collect_lots_from_listing(
            page,
            auction_discovery.AUCTION_INDEX_URL,
            "auction",
        )

        self.assertEqual(result, [])

    def test_structured_started_lot_skips_rendered_probe(self):
        lot = auction_lot()
        setattr(lot, "auction_start_state", guard.STARTED_STRUCTURED)
        self._set_collector([lot])
        page = FakePage(fail=True)

        result = guard.guarded_collect_lots_from_listing(
            page,
            auction_discovery.AUCTION_INDEX_URL,
            "auction",
        )

        self.assertEqual(result, [lot])
        self.assertEqual(page.goto_calls, [])

    def test_timerless_lot_stays_on_existing_inspect_item_fallback_path(self):
        lot = auction_lot(minutes=None)
        setattr(lot, "auction_start_state", guard.START_UNPROVEN)
        self._set_collector([lot])
        page = FakePage(fail=True)

        result = guard.guarded_collect_lots_from_listing(
            page,
            auction_discovery.AUCTION_INDEX_URL,
            "auction",
        )

        self.assertEqual(result, [lot])
        self.assertEqual(page.goto_calls, [])


class UpcomingAuctionInstallerTests(unittest.TestCase):
    def test_guard_wraps_whichever_collectors_are_current_at_install_time(self):
        saved_discover = auction_discovery.discover_auction_api_lots
        saved_inspect = watcher.inspect_item
        saved_collect = watcher.collect_lots_from_listing
        saved_base_discover = guard._BASE_DISCOVER_AUCTION_API_LOTS
        saved_base_inspect = guard._BASE_INSPECT_ITEM
        saved_base_collect = guard._BASE_COLLECT_LOTS_FROM_LISTING
        saved_installed = guard._INSTALLED_V4

        def current_collector(**_kwargs):
            return None

        def current_inspect(*_args, **_kwargs):
            return None

        def current_listing_collect(*_args, **_kwargs):
            return []

        try:
            auction_discovery.discover_auction_api_lots = current_collector
            watcher.inspect_item = current_inspect
            watcher.collect_lots_from_listing = current_listing_collect
            guard._INSTALLED_V4 = False
            guard.install_v4_upcoming_auction_guard()
            self.assertIs(guard._BASE_DISCOVER_AUCTION_API_LOTS, current_collector)
            self.assertIs(guard._BASE_INSPECT_ITEM, current_inspect)
            self.assertIs(guard._BASE_COLLECT_LOTS_FROM_LISTING, current_listing_collect)
            self.assertIs(
                auction_discovery.discover_auction_api_lots,
                guard.guarded_discover_auction_api_lots,
            )
            self.assertIs(watcher.inspect_item, guard.guarded_inspect_item)
            self.assertIs(
                watcher.collect_lots_from_listing,
                guard.guarded_collect_lots_from_listing,
            )
        finally:
            auction_discovery.discover_auction_api_lots = saved_discover
            watcher.inspect_item = saved_inspect
            watcher.collect_lots_from_listing = saved_collect
            guard._BASE_DISCOVER_AUCTION_API_LOTS = saved_base_discover
            guard._BASE_INSPECT_ITEM = saved_base_inspect
            guard._BASE_COLLECT_LOTS_FROM_LISTING = saved_base_collect
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
