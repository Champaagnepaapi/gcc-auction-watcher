import unittest
from datetime import datetime, timedelta, timezone

import run_watcher_safe
import watcher

NOW = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)


def make_lot(
    item_id: str,
    price: float = 50.0,
    title: str = "Pikachu",
    url: str = None,
) -> watcher.Lot:
    return watcher.Lot(
        url=url or f"https://example.com/items/{item_id}",
        title=title,
        current_price=price,
        source_type="fixed",
        grader="PSA",
        grade="10",
        card_number="25/102",
        card_set="Base Set",
        language="French",
        body="Catégorie: Pokémon\nRéférence: #25/102\nSérie: Base Set\nSociété de gradation: PSA\nNote: 10\n",
    )


class FixedQueueBacklogDiagnosticTests(unittest.TestCase):
    def test_stale_backlog_is_counted_without_downgrading_coverage(self):
        queue = watcher.FixedEconomicQueueDiagnostics(processing_budget=120)
        queue.initialized = True

        for index in range(227):
            queue.register(f"stale-{index}", watcher.QUEUE_P3_STALE)
        for index in range(120):
            queue.record_processed(f"stale-{index}")

        self.assertEqual(queue.coverage_backlog, 0)
        self.assertEqual(queue.queued_backlog, 107)
        self.assertEqual(queue.status, watcher.COVERAGE_COMPLETE)

        run_watcher_safe.install_fixed_queue_backlog_diagnostics()

        self.assertEqual(queue.estimated_backlog_runs, 1)
        summary = watcher.format_fixed_economic_queue(queue)
        self.assertIn("stale backlog: 107", summary)
        self.assertIn("estimated backlog runs remaining: 1", summary)
        self.assertIn("economic coverage: COMPLETE", summary)

    def test_backlog_run_estimate_uses_total_queue_and_budget(self):
        queue = watcher.FixedEconomicQueueDiagnostics(processing_budget=120)
        queue.initialized = True

        for index in range(241):
            queue.register(f"stale-{index}", watcher.QUEUE_P3_STALE)

        run_watcher_safe.install_fixed_queue_backlog_diagnostics()

        self.assertEqual(queue.queued_backlog, 241)
        self.assertEqual(queue.estimated_backlog_runs, 3)

    def test_external_pending_backlog_calculates_realistic_eta_and_blocks_coverage(self):
        """Invariant: 2253 P4 pending with max 10 P4 processed/run requires ~226 runs, not 19, and blocks complete external coverage."""
        queue = watcher.FixedEconomicQueueDiagnostics(processing_budget=120, p4_processing_budget=10)
        queue.initialized = True

        for index in range(2253):
            queue.register(f"pending-{index}", watcher.QUEUE_P4_EXTERNAL_PENDING)

        run_watcher_safe.install_fixed_queue_backlog_diagnostics()

        # First evaluation is complete (no P0/P1/P2 backlog)
        self.assertEqual(queue.first_evaluation_backlog, 0)
        self.assertEqual(queue.first_evaluation_coverage_status, watcher.COVERAGE_COMPLETE)

        # External market coverage is INCOMPLETE due to 2253 pending items
        self.assertEqual(queue.external_pending_backlog, 2253)
        self.assertEqual(queue.external_market_coverage_status, watcher.COVERAGE_INCOMPLETE)
        self.assertEqual(queue.status, watcher.COVERAGE_INCOMPLETE)

        # Realistic ETA must use P4 capacity (10/run), giving ceil(2253/10) = 226 runs, NOT ceil(2253/120) = 19
        self.assertEqual(queue.estimated_external_backlog_runs, 226)
        self.assertEqual(queue.estimated_backlog_runs, 226)

        diagnostics = watcher.RunDiagnostics()
        diagnostics.fixed_queue = queue
        diagnostics.fixed_coverage.set_end_reason("EOF")
        diagnostics.auction_coverage.set_end_reason("EOF")
        diagnostics.fixed_coverage.expected_total_scope = "COMPLETE"
        diagnostics.auction_coverage.expected_total_scope = "COMPLETE"
        diagnostics.fixed_economic_coverage.register_candidates([], discovered_listings=0)
        diagnostics.auction_economic_coverage.register_candidates([], discovered_listings=0)
        diagnostics.fixed_economic_coverage.finalized = True
        diagnostics.auction_economic_coverage.finalized = True

        # Scan text must truthfully reflect incomplete external coverage and untrustworthy overall result
        summary = watcher.format_scan_coverage(diagnostics)
        self.assertIn("FIRST_EVALUATION_COVERAGE: COMPLETE", summary)
        self.assertIn("EXTERNAL_MARKET_COVERAGE: INCOMPLETE", summary)
        self.assertIn("EXTERNAL_PENDING_BACKLOG: 2253", summary)
        self.assertIn("realistic backlog ETA: 226 runs", summary)
        self.assertIn("economic result trustworthy: NO", summary)





class FixedQueueFourTierSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            watcher.FIXED_QUEUE_STATE_KEY: {
                "schema_version": watcher.FIXED_QUEUE_SCHEMA_VERSION,
                "items": {},
            }
        }
        self.diagnostics = watcher.RunDiagnostics()

    def _setup_queue_items(
        self,
        p0_count=0,
        p1_count=0,
        p2_count=0,
        p3_count=0,
        p4_count=0,
        p4_cooldown_active=False,
    ):
        candidates = []
        items = self.state[watcher.FIXED_QUEUE_STATE_KEY]["items"]

        # P0: New items (not in state)
        for i in range(p0_count):
            lot = make_lot(f"p0-{i}", price=50.0)
            candidates.append(lot)

        # P1: Changed items (evaluated_fingerprint != metadata_fingerprint)
        for i in range(p1_count):
            lot = make_lot(f"p1-{i}", price=30.0)  # price dropped
            candidates.append(lot)
            item_id = watcher.fixed_listing_id(lot)
            items[item_id] = {
                "item_id": item_id,
                "first_seen_at": (NOW - timedelta(days=2)).isoformat(),
                "last_seen_at": (NOW - timedelta(hours=1)).isoformat(),
                "last_evaluated_at": (NOW - timedelta(hours=2)).isoformat(),
                "last_price": 50.0,
                "metadata_fingerprint": "old_fp",
                "evaluated_fingerprint": "old_fp",
                "evaluation_version": watcher.ECONOMIC_EVALUATION_VERSION,
                "last_evaluation_status": "weak_history",
                "retry_count": 0,
                "retry_after": None,
                "active": True,
            }

        # P2: Never evaluated items (in state but last_evaluated_at is None)
        for i in range(p2_count):
            lot = make_lot(f"p2-{i}", price=50.0)
            candidates.append(lot)
            item_id = watcher.fixed_listing_id(lot)
            items[item_id] = {
                "item_id": item_id,
                "first_seen_at": (NOW - timedelta(days=1)).isoformat(),
                "last_seen_at": (NOW - timedelta(hours=1)).isoformat(),
                "last_evaluated_at": None,
                "last_price": 50.0,
                "metadata_fingerprint": watcher.fixed_metadata_fingerprint(lot),
                "evaluated_fingerprint": None,
                "evaluation_version": None,
                "last_evaluation_status": None,
                "retry_count": 0,
                "retry_after": None,
                "active": True,
            }

        # P3: Stale items (evaluated > 24h ago)
        for i in range(p3_count):
            lot = make_lot(f"p3-{i}", price=50.0)
            candidates.append(lot)
            item_id = watcher.fixed_listing_id(lot)
            fp = watcher.fixed_metadata_fingerprint(lot)
            items[item_id] = {
                "item_id": item_id,
                "first_seen_at": (NOW - timedelta(days=3)).isoformat(),
                "last_seen_at": (NOW - timedelta(hours=1)).isoformat(),
                "last_evaluated_at": (NOW - timedelta(hours=25)).isoformat(),
                "last_price": 50.0,
                "metadata_fingerprint": fp,
                "evaluated_fingerprint": fp,
                "evaluation_version": watcher.ECONOMIC_EVALUATION_VERSION,
                "last_evaluation_status": "weak_history",
                "retry_count": 0,
                "retry_after": None,
                "active": True,
            }

        # P4: External pending / retry items
        for i in range(p4_count):
            lot = make_lot(f"p4-{i}", price=50.0)
            candidates.append(lot)
            item_id = watcher.fixed_listing_id(lot)
            fp = watcher.fixed_metadata_fingerprint(lot)
            retry_after = (
                (NOW + timedelta(minutes=15)).isoformat()
                if p4_cooldown_active
                else (NOW - timedelta(minutes=1)).isoformat()
            )
            items[item_id] = {
                "item_id": item_id,
                "first_seen_at": (NOW - timedelta(days=1)).isoformat(),
                "last_seen_at": (NOW - timedelta(hours=1)).isoformat(),
                "last_evaluated_at": (NOW - timedelta(minutes=30)).isoformat(),
                "last_price": 50.0,
                "metadata_fingerprint": fp,
                "evaluated_fingerprint": fp,
                "evaluation_version": watcher.ECONOMIC_EVALUATION_VERSION,
                "last_evaluation_status": watcher.REJECTION_EXTERNAL_PENDING,
                "retry_count": 1,
                "retry_after": retry_after,
                "active": True,
            }

        return candidates

    def test_200_p2_and_200_p3_and_50_eligible_p4_bounded_sharing(self):
        """Invariant: 10 P4 (hard cap), 90 P2, 20 P3 (stale floor) = 120 total."""
        candidates = self._setup_queue_items(
            p2_count=200, p3_count=200, p4_count=50, p4_cooldown_active=False
        )
        selected, cat_map, _ = watcher._prepare_fixed_economic_queue(
            candidates, self.state, NOW, self.diagnostics, valuation_cap=120
        )
        self.assertEqual(len(selected), 120)
        selected_cats = [cat_map[watcher.fixed_listing_id(lot)] for lot in selected]
        self.assertEqual(selected_cats.count(watcher.QUEUE_P4_EXTERNAL_PENDING), 10)
        self.assertEqual(selected_cats.count(watcher.QUEUE_P2_NEVER_EVALUATED), 90)
        self.assertEqual(selected_cats.count(watcher.QUEUE_P3_STALE), 20)

    def test_empty_p3_returns_all_unused_stale_capacity_to_p2(self):
        """Invariant: If P3 is empty, all 110 discovery slots go to P2."""
        candidates = self._setup_queue_items(
            p2_count=200, p3_count=0, p4_count=10, p4_cooldown_active=False
        )
        selected, cat_map, _ = watcher._prepare_fixed_economic_queue(
            candidates, self.state, NOW, self.diagnostics, valuation_cap=120
        )
        self.assertEqual(len(selected), 120)
        selected_cats = [cat_map[watcher.fixed_listing_id(lot)] for lot in selected]
        self.assertEqual(selected_cats.count(watcher.QUEUE_P4_EXTERNAL_PENDING), 10)
        self.assertEqual(selected_cats.count(watcher.QUEUE_P2_NEVER_EVALUATED), 110)
        self.assertEqual(selected_cats.count(watcher.QUEUE_P3_STALE), 0)

    def test_empty_p2_returns_all_unused_p2_capacity_to_p3(self):
        """Invariant: If P2 is empty, all 110 discovery slots go to P3."""
        candidates = self._setup_queue_items(
            p2_count=0, p3_count=200, p4_count=10, p4_cooldown_active=False
        )
        selected, cat_map, _ = watcher._prepare_fixed_economic_queue(
            candidates, self.state, NOW, self.diagnostics, valuation_cap=120
        )
        self.assertEqual(len(selected), 120)
        selected_cats = [cat_map[watcher.fixed_listing_id(lot)] for lot in selected]
        self.assertEqual(selected_cats.count(watcher.QUEUE_P4_EXTERNAL_PENDING), 10)
        self.assertEqual(selected_cats.count(watcher.QUEUE_P2_NEVER_EVALUATED), 0)
        self.assertEqual(selected_cats.count(watcher.QUEUE_P3_STALE), 110)

    def test_sparse_discovery_with_50_p4_hard_caps_p4_at_10(self):
        """Invariant: 5 P2 + 50 P4 selects exactly 5 P2 + 10 P4 = 15 total (never 50+)."""
        candidates = self._setup_queue_items(
            p2_count=5, p3_count=0, p4_count=50, p4_cooldown_active=False
        )
        selected, cat_map, _ = watcher._prepare_fixed_economic_queue(
            candidates, self.state, NOW, self.diagnostics, valuation_cap=120
        )
        self.assertEqual(len(selected), 15)
        selected_cats = [cat_map[watcher.fixed_listing_id(lot)] for lot in selected]
        self.assertEqual(selected_cats.count(watcher.QUEUE_P4_EXTERNAL_PENDING), 10)
        self.assertEqual(selected_cats.count(watcher.QUEUE_P2_NEVER_EVALUATED), 5)

    def test_urgent_surge_preempts_pending_and_discovery(self):
        """Invariant: 115 P1 + 50 P2 + 50 P3 + 50 P4 selects 115 P1 + 5 P4 + 0 P2 + 0 P3."""
        candidates = self._setup_queue_items(
            p1_count=115,
            p2_count=50,
            p3_count=50,
            p4_count=50,
            p4_cooldown_active=False,
        )
        selected, cat_map, _ = watcher._prepare_fixed_economic_queue(
            candidates, self.state, NOW, self.diagnostics, valuation_cap=120
        )
        self.assertEqual(len(selected), 120)
        selected_cats = [cat_map[watcher.fixed_listing_id(lot)] for lot in selected]
        self.assertEqual(selected_cats.count(watcher.QUEUE_P1_CHANGED), 115)
        self.assertEqual(selected_cats.count(watcher.QUEUE_P4_EXTERNAL_PENDING), 5)
        self.assertEqual(selected_cats.count(watcher.QUEUE_P2_NEVER_EVALUATED), 0)
        self.assertEqual(selected_cats.count(watcher.QUEUE_P3_STALE), 0)

    def test_cooldown_active_returns_fresh_and_expired_returns_p4(self):
        """Invariant: Active cooldown returns FRESH, expired returns P4_EXTERNAL_PENDING."""
        record_active = {
            "last_evaluated_at": NOW.isoformat(),
            "evaluated_fingerprint": "same",
            "evaluation_version": watcher.ECONOMIC_EVALUATION_VERSION,
            "last_evaluation_status": watcher.REJECTION_EXTERNAL_PENDING,
            "retry_count": 1,
            "retry_after": (NOW + timedelta(minutes=15)).isoformat(),
        }
        self.assertEqual(
            watcher._fixed_queue_category(record_active, "same", NOW),
            watcher.QUEUE_FRESH,
        )

        record_expired = {
            "last_evaluated_at": NOW.isoformat(),
            "evaluated_fingerprint": "same",
            "evaluation_version": watcher.ECONOMIC_EVALUATION_VERSION,
            "last_evaluation_status": watcher.REJECTION_EXTERNAL_PENDING,
            "retry_count": 1,
            "retry_after": (NOW - timedelta(seconds=1)).isoformat(),
        }
        self.assertEqual(
            watcher._fixed_queue_category(record_expired, "same", NOW),
            watcher.QUEUE_P4_EXTERNAL_PENDING,
        )

    def test_exponential_progression_of_retry_cooldown(self):
        """Invariant: Cooldown doubles: 15m -> 30m -> 60m -> 120m -> 240m -> 360m max."""
        lot = make_lot("item-exp")
        item_id = watcher.fixed_listing_id(lot)
        items = self.state[watcher.FIXED_QUEUE_STATE_KEY]["items"]
        items[item_id] = {
            "item_id": item_id,
            "first_seen_at": NOW.isoformat(),
            "last_seen_at": NOW.isoformat(),
            "last_evaluated_at": NOW.isoformat(),
            "last_price": 50.0,
            "metadata_fingerprint": watcher.fixed_metadata_fingerprint(lot),
            "evaluated_fingerprint": watcher.fixed_metadata_fingerprint(lot),
            "evaluation_version": watcher.ECONOMIC_EVALUATION_VERSION,
            "last_evaluation_status": "none",
            "retry_count": 0,
            "retry_after": None,
            "active": True,
        }

        expected_cooldowns = [15, 30, 60, 120, 240, 360, 360]
        for step, expected_mins in enumerate(expected_cooldowns, start=1):
            watcher._record_fixed_external_status(
                self.state,
                lot,
                watcher.REJECTION_EXTERNAL_PENDING,
                run_now=NOW,
            )
            rec = items[item_id]
            self.assertEqual(rec["retry_count"], step)
            expected_time = (NOW + timedelta(minutes=expected_mins)).isoformat()
            self.assertEqual(rec["retry_after"], expected_time)

    def test_success_resets_retry_state(self):
        """Invariant: Clean status resets retry_count to 0 and retry_after to None."""
        lot = make_lot("item-reset")
        item_id = watcher.fixed_listing_id(lot)
        items = self.state[watcher.FIXED_QUEUE_STATE_KEY]["items"]
        items[item_id] = {
            "item_id": item_id,
            "first_seen_at": NOW.isoformat(),
            "last_seen_at": NOW.isoformat(),
            "last_evaluated_at": NOW.isoformat(),
            "last_price": 50.0,
            "metadata_fingerprint": watcher.fixed_metadata_fingerprint(lot),
            "evaluated_fingerprint": watcher.fixed_metadata_fingerprint(lot),
            "evaluation_version": watcher.ECONOMIC_EVALUATION_VERSION,
            "last_evaluation_status": watcher.REJECTION_EXTERNAL_PENDING,
            "retry_count": 4,
            "retry_after": (NOW + timedelta(hours=4)).isoformat(),
            "active": True,
        }

        watcher._record_fixed_external_status(
            self.state, lot, "opportunity", run_now=NOW
        )
        rec = items[item_id]
        self.assertEqual(rec["retry_count"], 0)
        self.assertIsNone(rec["retry_after"])

    def test_material_fingerprint_change_resets_retry_count_and_clears_retry_after(
        self,
    ):
        """Invariant: Price drop resets retry backoff and puts item in P1_CHANGED."""
        lot = make_lot("item-changed", price=25.0)  # was 50.0
        item_id = watcher.fixed_listing_id(lot)
        items = self.state[watcher.FIXED_QUEUE_STATE_KEY]["items"]
        items[item_id] = {
            "item_id": item_id,
            "first_seen_at": NOW.isoformat(),
            "last_seen_at": NOW.isoformat(),
            "last_evaluated_at": (NOW - timedelta(hours=1)).isoformat(),
            "last_price": 50.0,
            "metadata_fingerprint": "old_fingerprint",
            "evaluated_fingerprint": "old_fingerprint",
            "evaluation_version": watcher.ECONOMIC_EVALUATION_VERSION,
            "last_evaluation_status": watcher.REJECTION_EXTERNAL_PENDING,
            "retry_count": 4,
            "retry_after": (NOW + timedelta(hours=4)).isoformat(),
            "active": True,
        }

        selected, cat_map, records = watcher._prepare_fixed_economic_queue(
            [lot], self.state, NOW, self.diagnostics, valuation_cap=120
        )
        self.assertEqual(cat_map[item_id], watcher.QUEUE_P1_CHANGED)
        self.assertEqual(records[item_id]["retry_count"], 0)
        self.assertIsNone(records[item_id]["retry_after"])

    def test_legacy_state_without_retry_fields_parsed_safely(self):
        """Invariant: Legacy state.json without retry fields defaults safely to P4."""
        record_legacy = {
            "item_id": "legacy-item",
            "first_seen_at": (NOW - timedelta(days=1)).isoformat(),
            "last_seen_at": NOW.isoformat(),
            "last_evaluated_at": (NOW - timedelta(hours=2)).isoformat(),
            "last_price": 50.0,
            "metadata_fingerprint": "same",
            "evaluated_fingerprint": "same",
            "evaluation_version": watcher.ECONOMIC_EVALUATION_VERSION,
            "last_evaluation_status": watcher.REJECTION_EXTERNAL_PENDING,
            # 'retry_count' and 'retry_after' are absent
        }
        category = watcher._fixed_queue_category(record_legacy, "same", NOW)
        self.assertEqual(category, watcher.QUEUE_P4_EXTERNAL_PENDING)


if __name__ == "__main__":
    unittest.main()
