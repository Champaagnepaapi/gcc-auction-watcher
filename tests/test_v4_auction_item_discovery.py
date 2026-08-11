from pathlib import Path
import unittest

import watcher
import v4_auction_item_discovery as discovery


CARD_34_MIN = """
PSA 10 Pikachu
Pokemon • Japanese • 2023 • SV-P Promos • Unlimited • #120/SV-P
60€
Private Auction
17 enchères • Fin le 10/08 @ 18h37
0 JOURS
:
0 HEURES
:
34 MINUTES
:
28 SEC
"""

CARD_65_MIN = """
PSA 10 Pikachu
Pokemon • Japanese • 2023 • SV-P Promos • Unlimited • #120/SV-P
60€
Private Auction
0 JOURS
:
1 HEURES
:
5 MINUTES
:
0 SEC
"""

BOOSTER_20_MIN = """
Booster EV1 Ecarlate et Violet
Pokemon • French • 2023 • Ecarlate et Violet
8€
Private Auction
0 JOURS
:
0 HEURES
:
20 MINUTES
:
0 SEC
"""

CARD_150_EUR = """
PSA 10 Pikachu
Pokemon • Japanese • 2023 • SV-P Promos • Unlimited • #120/SV-P
150€
Private Auction
0 JOURS
:
0 HEURES
:
20 MINUTES
:
0 SEC
"""

CARD_TIMERLESS = """
PSA 10 Pikachu
Pokemon • Japanese • 2023 • SV-P Promos • Unlimited • #120/SV-P
60€
Private Auction
"""


class ItemLevelAuctionClassificationTests(unittest.TestCase):
    def test_primary_url_is_global_auction_index(self):
        self.assertEqual(
            discovery.AUCTION_INDEX_URL,
            "https://gradedcardcenter.com/filtres/auctions",
        )

    def test_under_60_pokemon_card_in_budget_is_kept(self):
        result = discovery.classify_auction_listing(
            "https://gradedcardcenter.com/item/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "PSA 10 Pikachu",
            CARD_34_MIN,
            max_minutes=60,
        )
        self.assertIsNotNone(result.lot)
        self.assertIsNone(result.terminal_status)
        self.assertIsNotNone(result.timer_minutes)
        self.assertLessEqual(result.timer_minutes, 60)
        self.assertEqual(result.lot.source_type, "auction")
        self.assertEqual(result.lot.current_price, 60.0)

    def test_over_60_card_is_excluded_before_economic_analysis(self):
        result = discovery.classify_auction_listing(
            "https://gradedcardcenter.com/item/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "PSA 10 Pikachu",
            CARD_65_MIN,
            max_minutes=60,
        )
        self.assertIsNone(result.lot)
        self.assertEqual(result.terminal_status, watcher.ACCOUNT_EXCLUDED_BY_RULES)
        self.assertGreater(result.timer_minutes, 60)

    def test_sealed_product_is_excluded(self):
        result = discovery.classify_auction_listing(
            "https://gradedcardcenter.com/item/cccccccc-cccc-cccc-cccc-cccccccccccc",
            "Booster EV1",
            BOOSTER_20_MIN,
            max_minutes=60,
        )
        self.assertIsNone(result.lot)
        self.assertEqual(result.terminal_status, watcher.ACCOUNT_EXCLUDED_BY_RULES)

    def test_over_100_eur_is_excluded(self):
        result = discovery.classify_auction_listing(
            "https://gradedcardcenter.com/item/dddddddd-dddd-dddd-dddd-dddddddddddd",
            "PSA 10 Pikachu",
            CARD_150_EUR,
            max_minutes=60,
        )
        self.assertIsNone(result.lot)
        self.assertEqual(result.terminal_status, watcher.ACCOUNT_EXCLUDED_BY_RULES)

    def test_timerless_eligible_card_is_kept_for_existing_item_fallback(self):
        result = discovery.classify_auction_listing(
            "https://gradedcardcenter.com/item/eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
            "PSA 10 Pikachu",
            CARD_TIMERLESS,
            max_minutes=60,
        )
        self.assertIsNotNone(result.lot)
        self.assertIsNone(result.timer_minutes)
        self.assertIsNone(result.terminal_status)

    def test_timer_order_requires_near_monotonic_ending_first(self):
        self.assertTrue(discovery.timers_are_nondecreasing([5, 6, 6, 7, 20, 61]))
        self.assertTrue(discovery.timers_are_nondecreasing([5, 6, 5, 7, 20, 61]))
        self.assertFalse(discovery.timers_are_nondecreasing([5, 20, 8, 61]))
        self.assertFalse(discovery.timers_are_nondecreasing([5]))

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
