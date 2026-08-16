import unittest
from datetime import datetime, timezone

from v4_global_market_core import ACTIVE_AUCTION, AUCTION_SNAPSHOT_LE5, FIXED_ASK, CommercialIdentity
from v4_market_verified_offer import verified_auction_snapshot, verified_fixed_ask

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
ID = CommercialIdentity("Pikachu", "Pokemon 151", "173/165", "ja", "PSA", "10")


class VerifiedOfferAdapterTests(unittest.TestCase):
    def test_all_target_markets_can_feed_fixed_asks(self):
        for market in ("gcc", "cardova", "magi", "fanatics", "comc"):
            row = verified_fixed_ask(
                market=market,
                identity=ID,
                price=100,
                currency="EUR",
                observed_at=NOW,
                identity_proven=True,
            )
            self.assertEqual(row.source, market)
            self.assertEqual(row.evidence_type, FIXED_ASK)
            self.assertTrue(row.identity_proven)

    def test_unproven_identity_stays_blocked(self):
        row = verified_fixed_ask(
            market="fanatics",
            identity=ID,
            price=100,
            currency="USD",
            observed_at=NOW,
            identity_proven=False,
        )
        self.assertFalse(row.identity_proven)

    def test_unknown_market_rejected(self):
        with self.assertRaises(ValueError):
            verified_fixed_ask(
                market="unknown",
                identity=ID,
                price=100,
                currency="EUR",
                observed_at=NOW,
                identity_proven=True,
            )

    def test_auction_state_is_explicit(self):
        active = verified_auction_snapshot(
            market="fanatics",
            identity=ID,
            price=50,
            currency="USD",
            observed_at=NOW,
            end_at=NOW,
            within_five_minutes=False,
            identity_proven=True,
            buyer_fee_rate=0.20,
        )
        final = verified_auction_snapshot(
            market="fanatics",
            identity=ID,
            price=50,
            currency="USD",
            observed_at=NOW,
            end_at=NOW,
            within_five_minutes=True,
            identity_proven=True,
            buyer_fee_rate=0.20,
        )
        self.assertEqual(active.evidence_type, ACTIVE_AUCTION)
        self.assertEqual(final.evidence_type, AUCTION_SNAPSHOT_LE5)


if __name__ == "__main__":
    unittest.main()
