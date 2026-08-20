from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import v4_global_marketplace_discovery as discovery
import v4_global_marketplace_hardening as hardening
import v4_global_marketplace_queue as queue
from v4_global_market_core import FIXED_ASK, CommercialIdentity


NOW = datetime(2026, 8, 20, 16, 30, tzinfo=timezone.utc)


def _listing(source_id: str, name: str, number: str, price: float):
    identity = CommercialIdentity(name, "151", number, "en", "PSA", "10")
    return discovery.MarketplaceListing(
        "gcc",
        source_id,
        f"https://gradedcardcenter.com/item/{source_id}",
        name,
        identity,
        FIXED_ASK,
        price,
        "EUR",
        NOW,
        True,
    )


class MarketplaceQueueTests(unittest.TestCase):
    def test_attempts_survive_save_and_reload(self):
        listing = _listing("a", "Pikachu", "173/165", 50)
        state, _ = queue.reconcile_inventory_with_attempts(
            discovery.empty_discovery_state(), [listing], observed_at=NOW
        )
        state["attempts"][listing.stable_key] = 3
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "discovery.json"
            discovery.save_discovery_state(path, state)
            loaded, status = queue.load_discovery_state_with_attempts(path, strict=True)
        self.assertEqual(status, "STATE_LOADED")
        self.assertEqual(loaded["attempts"][listing.stable_key], 3)

    def test_unattempted_listing_beats_high_discount_retry(self):
        retry = _listing("retry", "Pikachu", "173/165", 20)
        fresh = _listing("fresh", "Mewtwo", "183/165", 70)
        state = {
            "pending": [retry.stable_key, fresh.stable_key],
            "attempts": {retry.stable_key: 1, fresh.stable_key: 0},
        }
        hardening._LAST_FAIR = {
            retry.identity.strict_key: 100.0,
            fresh.identity.strict_key: 100.0,
        }
        selected, keys = queue.select_pending_fair_round_robin(
            state, {retry.stable_key: retry, fresh.stable_key: fresh}, limit=1
        )
        self.assertEqual(selected[0].source_id, "fresh")
        self.assertEqual(keys, [fresh.stable_key])

    def test_known_discount_prioritizes_inside_same_attempt_round(self):
        small = _listing("small", "Pikachu", "173/165", 80)
        large = _listing("large", "Mewtwo", "183/165", 40)
        state = {
            "pending": [small.stable_key, large.stable_key],
            "attempts": {small.stable_key: 0, large.stable_key: 0},
        }
        hardening._LAST_FAIR = {
            small.identity.strict_key: 100.0,
            large.identity.strict_key: 100.0,
        }
        selected, _ = queue.select_pending_fair_round_robin(
            state, {small.stable_key: small, large.stable_key: large}, limit=1
        )
        self.assertEqual(selected[0].source_id, "large")

    def test_selection_increments_attempt_before_state_save(self):
        listing = _listing("a", "Pikachu", "173/165", 50)
        state = {"pending": [listing.stable_key], "attempts": {listing.stable_key: 0}}
        queue.select_pending_fair_round_robin(state, {listing.stable_key: listing}, limit=1)
        self.assertEqual(state["attempts"][listing.stable_key], 1)

    def test_changed_listing_requeues_with_fresh_attempt_round(self):
        old = _listing("a", "Pikachu", "173/165", 80)
        state, _ = queue.reconcile_inventory_with_attempts(
            discovery.empty_discovery_state(), [old], observed_at=NOW
        )
        state["attempts"][old.stable_key] = 2
        state = discovery.acknowledge_evaluated(state, [old.stable_key])
        changed = _listing("a", "Pikachu", "173/165", 60)
        state2, stats = queue.reconcile_inventory_with_attempts(
            state, [changed], observed_at=NOW
        )
        self.assertEqual(stats["changed"], 1)
        self.assertEqual(state2["attempts"][changed.stable_key], 0)

    def test_strict_corruption_gate_is_not_weakened(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "discovery.json"
            path.write_text("not-json", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "GLOBAL_MARKETPLACE_DISCOVERY_STATE_INVALID"):
                queue.load_discovery_state_with_attempts(path, strict=True)


if __name__ == "__main__":
    unittest.main()
