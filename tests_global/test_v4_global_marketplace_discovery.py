from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import v4_global_marketplace_discovery as discovery
from v4_global_market_core import ACTIVE_AUCTION, FIXED_ASK, CommercialIdentity


NOW = datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc)


def _identity() -> CommercialIdentity:
    return CommercialIdentity(
        name="Mewtwo",
        set_name="151",
        number="183/165",
        language="ja",
        grader="PSA",
        grade="10",
    )


def _listing(price: float = 70.0, source_id: str = "abc") -> discovery.MarketplaceListing:
    return discovery.MarketplaceListing(
        market="fanatics",
        source_id=source_id,
        source_url=f"https://fanatics.invalid/{source_id}",
        title="Mewtwo",
        identity=_identity(),
        evidence_type=FIXED_ASK,
        price=price,
        currency="EUR",
        observed_at=NOW,
        identity_proven=True,
    )


class MarketplaceDiscoveryTests(unittest.TestCase):
    def test_bootstrap_enqueues_existing_inventory_for_evaluation(self):
        listings = [_listing(), _listing(source_id="def")]
        state, stats = discovery.reconcile_inventory(
            discovery.empty_discovery_state(),
            listings,
            observed_at=NOW,
        )
        self.assertEqual(stats["new"], 2)
        self.assertEqual(stats["pending_total"], 2)
        current = {listing.stable_key: listing for listing in listings}
        selected, keys = discovery.select_pending_listings(state, current, limit=10)
        self.assertEqual(len(selected), 2)
        self.assertEqual(len(keys), 2)

    def test_unchanged_listing_not_requeued_after_acknowledge(self):
        listing = _listing()
        state, _ = discovery.reconcile_inventory(discovery.empty_discovery_state(), [listing], observed_at=NOW)
        state = discovery.acknowledge_evaluated(state, [listing.stable_key])
        state, stats = discovery.reconcile_inventory(state, [listing], observed_at=NOW + timedelta(hours=1))
        self.assertEqual(stats["unchanged"], 1)
        self.assertEqual(state["pending"], [])

    def test_price_change_requeues_listing(self):
        first = _listing(70)
        state, _ = discovery.reconcile_inventory(discovery.empty_discovery_state(), [first], observed_at=NOW)
        state = discovery.acknowledge_evaluated(state, [first.stable_key])
        changed = _listing(60)
        state, stats = discovery.reconcile_inventory(state, [changed], observed_at=NOW + timedelta(hours=1))
        self.assertEqual(stats["changed"], 1)
        self.assertEqual(state["pending"], [changed.stable_key])

    def test_missing_listing_is_not_fabricated_as_sold(self):
        listing = _listing()
        state, _ = discovery.reconcile_inventory(discovery.empty_discovery_state(), [listing], observed_at=NOW)
        state = discovery.acknowledge_evaluated(state, [listing.stable_key])
        state2, stats = discovery.reconcile_inventory(
            state,
            [],
            observed_at=NOW + timedelta(hours=1),
            complete_markets={"fanatics"},
        )
        self.assertEqual(stats["seen"], 0)
        self.assertEqual(stats["missing_not_sold"], 1)
        self.assertIn(listing.stable_key, state2["listings"])
        self.assertTrue(state2["listings"][listing.stable_key]["missing_since"])
        self.assertNotIn("evidence_type\": \"SOLD", str(state2))

    def test_state_roundtrip_and_strict_corruption_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state, _ = discovery.reconcile_inventory(discovery.empty_discovery_state(), [_listing()], observed_at=NOW)
            discovery.save_discovery_state(path, state)
            loaded, status = discovery.load_discovery_state(path, strict=True)
            self.assertEqual(status, "STATE_LOADED")
            self.assertEqual(loaded["pending"], state["pending"])
            path.write_text("not-json", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "GLOBAL_MARKETPLACE_DISCOVERY_STATE_INVALID"):
                discovery.load_discovery_state(path, strict=True)

    def test_gcc_structured_inventory_supports_en_and_ja_psa_production_grades(self):
        row = {
            "id": "gcc-1",
            "status": "ON_SALE",
            "sellingTypeGroup": "FIXED_PRICE",
            "priceInCents": 9900,
            "item": {
                "gradingCompany": "PSA",
                "grade": "9",
                "collectible": {
                    "category": "Pokemon",
                    "type": "Cards",
                    "language": "English",
                    "character": {"englishName": "Pikachu"},
                    "set": "151",
                    "reference": "173/165",
                },
            },
        }
        listing = discovery.gcc_listing_from_row(row, observed_at=NOW)
        self.assertIsNotNone(listing)
        self.assertEqual(listing.identity.language, "en")
        self.assertEqual(listing.identity.grade, "9")
        self.assertEqual(listing.evidence_type, FIXED_ASK)

    def test_active_auction_remains_non_actionable_and_never_sold(self):
        row = {
            "id": "gcc-a",
            "status": "ON_SALE",
            "sellingTypeGroup": "AUCTION",
            "priceInCents": 5000,
            "endTime": (NOW + timedelta(minutes=30)).isoformat(),
            "item": {
                "gradingCompany": "PSA",
                "grade": "10",
                "collectible": {
                    "category": "Pokemon",
                    "type": "Cards",
                    "language": "Japanese",
                    "character": {"englishName": "Mewtwo"},
                    "set": "151",
                    "reference": "183/165",
                },
            },
        }
        listing = discovery.gcc_listing_from_row(row, observed_at=NOW)
        self.assertEqual(listing.evidence_type, ACTIVE_AUCTION)
        self.assertNotIn("SOLD", listing.evidence_type)

    def test_cards_from_listings_keeps_external_only_possible(self):
        cards = discovery.cards_from_listings(
            [_listing()],
            currency_per_eur={},
            gcc_fair_by_identity={},
            observed_at=NOW,
        )
        self.assertEqual(len(cards), 1)
        self.assertNotIn("fair_value_eur", cards[0])
        self.assertEqual(cards[0]["offers"][0]["all_in_eur"], 70.0)


if __name__ == "__main__":
    unittest.main()
