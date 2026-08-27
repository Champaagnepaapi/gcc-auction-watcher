from __future__ import annotations

from datetime import datetime, timezone
import unittest

import watcher
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
    def test_future_start_is_explicitly_upcoming(self):
        row = auction_row(start_time="2026-08-27T19:00:00Z")
        self.assertTrue(guard.is_upcoming_auction_row(row, observed_at=NOW))

    def test_started_auction_is_not_upcoming(self):
        row = auction_row(start_time="2026-08-27T18:00:00Z")
        self.assertFalse(guard.is_upcoming_auction_row(row, observed_at=NOW))

    def test_missing_start_time_is_not_guessed(self):
        self.assertFalse(
            guard.is_upcoming_auction_row(auction_row(), observed_at=NOW)
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
        self.assertEqual(
            getattr(result.coverage, "auction_upcoming_excluded", 0), 1
        )
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
            getattr(result.coverage, "auction_upcoming_excluded", 0), 0
        )


class UpcomingAuctionRenderedGuardTests(unittest.TestCase):
    def test_gcc_upcoming_page_markers_are_deterministic(self):
        body = (
            "Enchères à venir\n"
            "Début le jeudi 27.08.2026 à 21h00\n"
            "10€\nProgrammer une enchère"
        )
        self.assertTrue(guard.rendered_page_proves_upcoming(body))
        self.assertFalse(
            guard.rendered_page_proves_upcoming(
                "Weekly Auction\n17 enchères\nFin le 27/08 à 21h00\nEnchérir"
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


if __name__ == "__main__":
    unittest.main()
