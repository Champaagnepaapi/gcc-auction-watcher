from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

import watcher
import v4_auction_item_discovery as discovery
import v4_auction_coverage_hardening as hardening


NOW = datetime(2026, 8, 31, 19, 30, tzinfo=timezone.utc)


def api_row(row_id: str, *, end_time: str, price_cents: int = 6000) -> dict:
    return {
        "id": row_id,
        "status": "ON_SALE",
        "price": price_cents / 100,
        "priceInCents": price_cents,
        "sellingType": "AUCTION",
        "endTime": end_time,
        "bidsNumber": 2,
        "item": {
            "title": "Pikachu",
            "gradingCompany": "PSA",
            "grade": "10",
            "collectible": {
                "category": "Pokemon",
                "language": "Japanese",
                "yearOfDistribution": "2023",
                "extension": "SV-P Promos",
                "set": "SV-P Promos",
                "reference": "120/SV-P",
                "type": "CARDS",
            },
        },
    }


def api_payload(page: int, rows: list[dict], *, next_page=None, total=None) -> dict:
    info = {"currentPage": page, "nextPage": next_page}
    if total is not None:
        info["counts"] = {
            "total": total,
            "auctionCount": total,
            "fixedPriceCount": 0,
        }
    return {"info": info, "results": rows}


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload
        self.headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeGet:
    def __init__(self, payloads: list[dict]):
        self.payloads = list(payloads)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.payloads:
            raise AssertionError("unexpected extra API call")
        return FakeResponse(self.payloads.pop(0))


class _Queue:
    first_evaluation_coverage_status = watcher.COVERAGE_COMPLETE
    first_evaluation_backlog = 0
    external_market_coverage_status = watcher.COVERAGE_INCOMPLETE
    external_pending_backlog = 2272
    fresh_already_evaluated = 452

    def budget_skipped_count(self, category):
        return 0

    def backlog_count(self, category):
        if category == watcher.QUEUE_P2_NEVER_EVALUATED:
            return 0
        return 0


class AuctionCoverageHardeningTests(unittest.TestCase):
    def test_non_monotonic_order_is_diagnostic_when_filtered_query_is_exhausted(self):
        getter = FakeGet(
            [
                api_payload(
                    1,
                    [
                        api_row(
                            "11111111-1111-1111-1111-111111111111",
                            end_time="2026-08-31T20:20:00Z",
                        )
                    ],
                    next_page=2,
                    total=3,
                ),
                api_payload(
                    2,
                    [
                        api_row(
                            "22222222-2222-2222-2222-222222222222",
                            end_time="2026-08-31T20:00:00Z",
                        )
                    ],
                    next_page=3,
                ),
                api_payload(
                    3,
                    [
                        api_row(
                            "33333333-3333-3333-3333-333333333333",
                            end_time="2026-08-31T20:40:00Z",
                        )
                    ],
                    next_page=None,
                ),
            ]
        )

        result = hardening.discover_auction_api_lots_exhaustive(
            max_minutes=60,
            http_get=getter,
            page_size=1,
            now=NOW,
        )

        self.assertTrue(result.complete)
        self.assertEqual(result.scope_status, discovery.PRIMARY_SCOPE_STATUS)
        self.assertFalse(result.order_verified)
        self.assertTrue(result.threshold_crossed)
        self.assertEqual(len(getter.calls), 3)
        self.assertEqual(
            {lot.url.rsplit("/", 1)[-1] for lot in result.lots},
            {
                "11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
            },
        )
        excluded = "https://gradedcardcenter.com/item/33333333-3333-3333-3333-333333333333"
        self.assertEqual(
            result.coverage.terminal_statuses.get(excluded),
            watcher.ACCOUNT_EXCLUDED_BY_RULES,
        )

    def test_horizon_crossing_never_stops_before_a_later_urgent_row(self):
        getter = FakeGet(
            [
                api_payload(
                    1,
                    [
                        api_row(
                            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                            end_time="2026-08-31T20:40:00Z",
                        )
                    ],
                    next_page=2,
                    total=2,
                ),
                api_payload(
                    2,
                    [
                        api_row(
                            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                            end_time="2026-08-31T19:50:00Z",
                        )
                    ],
                    next_page=None,
                ),
            ]
        )

        result = hardening.discover_auction_api_lots_exhaustive(
            max_minutes=60,
            http_get=getter,
            page_size=1,
            now=NOW,
        )

        self.assertTrue(result.complete)
        self.assertFalse(result.order_verified)
        self.assertEqual(len(getter.calls), 2)
        self.assertEqual(len(result.lots), 1)
        self.assertTrue(result.lots[0].url.endswith("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"))
        self.assertLessEqual(result.lots[0].minutes_to_end, 60)

    def test_structural_failure_remains_fail_closed(self):
        getter = FakeGet(
            [
                api_payload(
                    1,
                    [
                        api_row(
                            "11111111-1111-1111-1111-111111111111",
                            end_time="",
                        )
                    ],
                    next_page=None,
                    total=1,
                )
            ]
        )

        result = hardening.discover_auction_api_lots_exhaustive(
            max_minutes=60,
            http_get=getter,
            now=NOW,
        )

        self.assertFalse(result.complete)
        self.assertEqual(result.lots, [])
        self.assertEqual(result.scope_status, discovery.FALLBACK_SCOPE_STATUS)

    def test_alert_text_separates_external_pending_from_unseen_fixed_cards(self):
        diagnostics = SimpleNamespace(
            fixed_coverage=SimpleNamespace(
                unique_listings=3175,
                expected_total=3175,
                status=watcher.COVERAGE_COMPLETE,
            ),
            auction_coverage=SimpleNamespace(
                unique_listings=112,
                status=watcher.COVERAGE_INCOMPLETE,
            ),
            fixed_economic_coverage=SimpleNamespace(attempted=19),
            auction_economic_coverage=SimpleNamespace(
                attempted=42,
                candidates=42,
                status=watcher.COVERAGE_COMPLETE,
                skipped_by_cap=0,
            ),
            fixed_queue=_Queue(),
            auction_discovery_scope_status=discovery.FALLBACK_SCOPE_STATUS,
            state_issue="",
            discovery_coverage_status=watcher.COVERAGE_INCOMPLETE,
            economic_coverage_status=watcher.COVERAGE_INCOMPLETE,
            scan_coverage_status=watcher.COVERAGE_INCOMPLETE,
            economic_result_trustworthy=False,
        )

        message = hardening.format_actionable_technical_coverage_message(diagnostics)

        self.assertIn("Fixed first-evaluation: COMPLETE | backlog 0", message)
        self.assertIn("pending retry 2272", message)
        self.assertIn("fresh already evaluated 452", message)
        self.assertIn("Never-evaluated fixed backlog: 0", message)
        self.assertNotIn("cap skipped 2224", message)


if __name__ == "__main__":
    unittest.main()
