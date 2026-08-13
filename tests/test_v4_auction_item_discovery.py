from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import unittest

import watcher
import v4_auction_item_discovery as discovery


NOW = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)


def api_row(
    row_id: str,
    *,
    end_time: str,
    price_cents: int = 6000,
    title: str = "Pikachu",
    category: str = "Pokemon",
    item_type: str = "CARDS",
) -> dict:
    return {
        "id": row_id,
        "status": "ON_SALE",
        "price": price_cents / 100,
        "priceInCents": price_cents,
        "sellingType": "AUCTION",
        "endTime": end_time,
        "bidsNumber": 3,
        "item": {
            "title": title,
            "gradingCompany": "PSA",
            "grade": "10",
            "collectible": {
                "category": category,
                "language": "Japanese",
                "yearOfDistribution": "2023",
                "extension": "SV-P Promos",
                "set": "SV-P Promos",
                "reference": "120/SV-P",
                "type": item_type,
            },
        },
    }


def api_payload(
    page: int,
    results: list[dict],
    *,
    next_page=None,
    total: int | None = None,
) -> dict:
    info = {"currentPage": page, "nextPage": next_page}
    if total is not None:
        info["counts"] = {
            "total": total,
            "auctionCount": total,
            "fixedPriceCount": 0,
        }
    return {"info": info, "results": results}


class FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload
        self.headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeGet:
    def __init__(self, payloads: list[dict]):
        self.payloads = list(payloads)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.payloads:
            raise AssertionError("unexpected extra API call")
        return FakeResponse(self.payloads.pop(0))


class AuctionApiDiscoveryTests(unittest.TestCase):
    def test_primary_page_and_api_are_the_official_gcc_sources(self):
        self.assertEqual(
            discovery.AUCTION_INDEX_URL,
            "https://gradedcardcenter.com/filtres/auctions",
        )
        self.assertEqual(discovery.AUCTION_API_URL, watcher.GCC_ON_SALE_ITEMS_API_URL)

    def test_end_time_is_converted_to_minutes(self):
        parsed = discovery._parse_api_end_time(
            "2026-08-11T08:34:28Z",
            now=NOW,
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.minutes, 35)
        self.assertEqual(parsed.at.tzinfo, timezone.utc)

    def test_item_level_api_keeps_only_pokemon_cards_in_budget_within_horizon(self):
        getter = FakeGet(
            [
                api_payload(
                    1,
                    [
                        api_row(
                            "11111111-1111-1111-1111-111111111111",
                            end_time="2026-08-11T08:30:00Z",
                            price_cents=6000,
                        ),
                        api_row(
                            "22222222-2222-2222-2222-222222222222",
                            end_time="2026-08-11T08:40:00Z",
                            price_cents=15000,
                        ),
                        api_row(
                            "33333333-3333-3333-3333-333333333333",
                            end_time="2026-08-11T08:50:00Z",
                            title="Booster EV1",
                            item_type="SEALED_PRODUCTS",
                        ),
                        api_row(
                            "44444444-4444-4444-4444-444444444444",
                            end_time="2026-08-11T09:05:00Z",
                            price_cents=5000,
                        ),
                    ],
                    next_page=2,
                    total=4000,
                )
            ]
        )
        result = discovery.discover_auction_api_lots(
            max_minutes=60,
            http_get=getter,
            now=NOW,
        )

        self.assertTrue(result.complete)
        self.assertEqual(result.scope_status, discovery.PRIMARY_SCOPE_STATUS)
        self.assertTrue(result.threshold_crossed)
        self.assertTrue(result.order_verified)
        self.assertEqual(result.rows_seen, 4)
        self.assertEqual(result.timers_parsed, 4)
        self.assertEqual(result.api_total, 4000)
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(result.lots[0].current_price, 60.0)
        self.assertEqual(result.lots[0].source_type, "auction")
        self.assertEqual(result.lots[0].minutes_to_end, 30)
        self.assertEqual(len(getter.calls), 1)

        params = getter.calls[0][1]["params"]
        self.assertEqual(params["sellingTypeGroup"], "AUCTION")
        self.assertEqual(params["sortType"], "ENDING_SOON")
        self.assertEqual(params["status"], "ON_SALE")

    def test_api_paginates_until_horizon_is_crossed(self):
        getter = FakeGet(
            [
                api_payload(
                    1,
                    [
                        api_row(
                            "11111111-1111-1111-1111-111111111111",
                            end_time="2026-08-11T08:20:00Z",
                        )
                    ],
                    next_page=2,
                    total=2,
                ),
                api_payload(
                    2,
                    [
                        api_row(
                            "22222222-2222-2222-2222-222222222222",
                            end_time="2026-08-11T09:10:00Z",
                        )
                    ],
                    next_page=None,
                ),
            ]
        )
        result = discovery.discover_auction_api_lots(
            max_minutes=60,
            http_get=getter,
            page_size=1,
            now=NOW,
        )
        self.assertTrue(result.complete)
        self.assertTrue(result.threshold_crossed)
        self.assertEqual(result.coverage.pages_requested, 2)
        self.assertEqual(len(result.lots), 1)
        self.assertEqual(len(getter.calls), 2)

    def test_api_can_prove_complete_when_inventory_is_exhausted_inside_horizon(self):
        getter = FakeGet(
            [
                api_payload(
                    1,
                    [
                        api_row(
                            "11111111-1111-1111-1111-111111111111",
                            end_time="2026-08-11T08:20:00Z",
                        )
                    ],
                    next_page=None,
                    total=1,
                )
            ]
        )
        result = discovery.discover_auction_api_lots(
            max_minutes=60,
            http_get=getter,
            now=NOW,
        )
        self.assertTrue(result.complete)
        self.assertFalse(result.threshold_crossed)
        self.assertEqual(result.reason, discovery.PRIMARY_EXHAUSTED_REASON)
        self.assertEqual(len(result.lots), 1)

    def test_non_monotonic_ending_soon_response_never_claims_complete(self):
        getter = FakeGet(
            [
                api_payload(
                    1,
                    [
                        api_row(
                            "11111111-1111-1111-1111-111111111111",
                            end_time="2026-08-11T08:50:00Z",
                        ),
                        api_row(
                            "22222222-2222-2222-2222-222222222222",
                            end_time="2026-08-11T08:30:00Z",
                        ),
                    ],
                    next_page=None,
                    total=2,
                )
            ]
        )
        result = discovery.discover_auction_api_lots(
            max_minutes=60,
            http_get=getter,
            now=NOW,
        )
        self.assertFalse(result.complete)
        self.assertEqual(result.scope_status, discovery.FALLBACK_SCOPE_STATUS)
        self.assertEqual(result.lots, [])

    def test_missing_end_time_never_claims_sorted_horizon_complete(self):
        row = api_row(
            "11111111-1111-1111-1111-111111111111",
            end_time="2026-08-11T08:30:00Z",
        )
        row["endTime"] = None
        getter = FakeGet([api_payload(1, [row], next_page=None, total=1)])
        result = discovery.discover_auction_api_lots(
            max_minutes=60,
            http_get=getter,
            now=NOW,
        )
        self.assertFalse(result.complete)
        self.assertEqual(result.lots, [])
        self.assertIn("endTime", result.reason)

    def test_scoped_complete_status_maps_to_generic_complete_without_claiming_all_gcc(self):
        coverage = watcher.CoverageAudit("AUCTIONS", watcher.AUCTION_DISCOVERY_FILTERS)
        coverage.protocol = discovery.PRIMARY_PROTOCOL
        coverage._auction_scope_complete = True
        coverage.auction_scope_status = discovery.PRIMARY_SCOPE_STATUS
        self.assertEqual(
            discovery.patched_coverage_status(coverage),
            watcher.COVERAGE_COMPLETE,
        )
        self.assertEqual(
            coverage.auction_scope_status,
            "COMPLETE_FOR_DISCOVERED_AUCTION_LISTINGS",
        )

        coverage.incomplete_reasons.append("synthetic parse failure")
        self.assertEqual(
            discovery.patched_coverage_status(coverage),
            watcher.COVERAGE_INCOMPLETE,
        )

    def test_legacy_collectors_are_preserved_as_fallback(self):
        self.assertTrue(callable(discovery._ORIGINAL_COLLECT_LIVE_AUCTION_URLS))
        self.assertTrue(callable(discovery._ORIGINAL_COLLECT_LOTS_FROM_LISTING))
        self.assertIsNot(
            discovery._ORIGINAL_COLLECT_LOTS_FROM_LISTING,
            discovery.patched_collect_lots_from_listing,
        )


class ProductionWiringTests(unittest.TestCase):
    def test_safe_entrypoint_installs_item_level_discovery(self):
        source = Path("run_watcher_safe.py").read_text(encoding="utf-8")
        self.assertIn("install_v4_auction_item_discovery", source)
        self.assertIn("install_grade_arbitrage_guard()", source)
        self.assertIn("install_v4_auction_item_discovery()", source)

    def test_production_workflow_logs_trigger_and_auction_counters(self):
        workflow = Path(".github/workflows/watcher.yml").read_text(encoding="utf-8")
        self.assertIn("trigger=${context.eventName}", workflow)
        self.assertIn("auction_discovery_mode", workflow)
        self.assertIn("auction_scope_status", workflow)
        self.assertIn("auction_discovered_rows", workflow)
        self.assertIn("auction_timer_parsed", workflow)
        self.assertIn("auction_ending_soon", workflow)
        self.assertIn("auction_fallback_used", workflow)


if __name__ == "__main__":
    unittest.main()
