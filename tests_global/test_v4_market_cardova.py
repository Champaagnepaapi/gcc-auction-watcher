import unittest
from datetime import datetime, timedelta, timezone

from v4_global_market_core import ACTIVE_AUCTION, AUCTION_SNAPSHOT_LE5, FINISHED_UNPROVEN, FIXED_ASK
from v4_market_cardova import parse_auction_payload, parse_fixed_payload


NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


class CardovaAdapterTests(unittest.TestCase):
    def test_fixed_direct_single_only(self):
        payload = {"list": [
            {"ulid":"a", "listing_type":4, "asking_price":120000, "set_quantity":1, "authentication_company_code":"P", "grade":"10.0", "language":"Japanese", "player":"Charizard ex", "variety":"Pokemon Card 151", "card_number":"#201/165", "attribute":"SAR"},
            {"ulid":"bundle", "listing_type":5, "set_asking_price":200000, "set_quantity":2, "authentication_company_code":"P", "grade":"10.0", "language":"Japanese", "player":"Charizard ex", "variety":"Pokemon Card 151", "card_number":"#201/165"},
        ]}
        rows = parse_fixed_payload(payload, observed_at=NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].evidence_type, FIXED_ASK)
        self.assertEqual(rows[0].identity.language, "ja")
        self.assertEqual(rows[0].identity.grader, "PSA")
        self.assertTrue(rows[0].identity_proven)

    def test_auction_active_and_le5_are_distinct(self):
        payload = {"list": [
            {"ulid":"early", "listing_type":1, "finished":0, "bid_price":1000, "start_price":1000, "end_date":(NOW+timedelta(hours=2)).isoformat(), "authentication_company_code":"P", "grade":"10.0", "language":"Japanese", "player":"Pikachu", "variety":"Pokemon 151", "card_number":"#173/165"},
            {"ulid":"late", "listing_type":1, "finished":0, "bid_price":5000, "start_price":1000, "end_date":(NOW+timedelta(minutes=4)).isoformat(), "authentication_company_code":"P", "grade":"10.0", "language":"Japanese", "player":"Pikachu", "variety":"Pokemon 151", "card_number":"#173/165"},
        ]}
        rows = parse_auction_payload(payload, observed_at=NOW, buyer_premium_rate=0.11)
        by_id = {row.source_id: row for row in rows}
        self.assertEqual(by_id["early"].evidence_type, ACTIVE_AUCTION)
        self.assertEqual(by_id["late"].evidence_type, AUCTION_SNAPSHOT_LE5)

    def test_finished_auction_is_not_promoted_to_sold(self):
        payload = {"list": [{"ulid":"done", "listing_type":1, "finished":1, "bid_price":9000, "start_price":1000, "end_date":NOW.isoformat(), "authentication_company_code":"P", "grade":"10.0", "language":"Japanese", "player":"Pikachu", "variety":"Pokemon 151", "card_number":"#173/165"}]}
        row = parse_auction_payload(payload, observed_at=NOW, buyer_premium_rate=0.11)[0]
        self.assertEqual(row.evidence_type, FINISHED_UNPROVEN)
        self.assertFalse(row.is_exact_sold)

    def test_unknown_buyer_premium_fails_closed_for_all_in(self):
        payload = {"list": [{"ulid":"early", "listing_type":1, "finished":0, "bid_price":1000, "start_price":1000, "end_date":(NOW+timedelta(hours=2)).isoformat(), "authentication_company_code":"P", "grade":"10.0", "language":"Japanese", "player":"Pikachu", "variety":"Pokemon 151", "card_number":"#173/165"}]}
        row = parse_auction_payload(payload, observed_at=NOW, buyer_premium_rate=None)[0]
        self.assertIsNone(row.buyer_fee_rate)

    def test_non_en_ja_identity_is_preserved_but_not_proven_for_opportunity(self):
        payload = {"list": [{"ulid":"fr", "listing_type":4, "asking_price":10000, "set_quantity":1, "authentication_company_code":"P", "grade":"10.0", "language":"French", "player":"Pikachu", "variety":"Pokemon 151", "card_number":"#173/165"}]}
        row = parse_fixed_payload(payload, observed_at=NOW)[0]
        self.assertEqual(row.identity.language, "fr")
        self.assertFalse(row.identity_proven)


if __name__ == "__main__":
    unittest.main()
