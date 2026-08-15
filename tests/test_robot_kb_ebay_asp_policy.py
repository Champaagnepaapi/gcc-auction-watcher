from __future__ import annotations

import unittest

from robot_kb_ebay_asp_policy import (
    CandidateContext,
    LookupStatus,
    PriceConfidence,
    QuotaImpactTelemetry,
    choose_lookup,
    dedupe_global,
    normalize_sale_row,
    same_english_card_across_marketplaces,
)


class EbayAspPolicyTests(unittest.TestCase):
    def test_cache_then_us_then_uk_policy(self) -> None:
        candidate = CandidateContext(True, True)
        self.assertEqual(choose_lookup(candidate, remaining_requests=50).status, LookupStatus.QUERY_US)
        self.assertEqual(choose_lookup(candidate, remaining_requests=49, us_strong_sold=2).status, LookupStatus.QUERY_UK_FALLBACK)
        self.assertEqual(choose_lookup(candidate, remaining_requests=49, us_strong_sold=3).status, LookupStatus.CACHE_SUFFICIENT)
        cached = CandidateContext(True, True, cached_strong_sold=3)
        self.assertEqual(choose_lookup(cached, remaining_requests=50).status, LookupStatus.CACHE_SUFFICIENT)

    def test_quota_exhaustion_is_pending_not_negative(self) -> None:
        result = choose_lookup(CandidateContext(True, True), remaining_requests=0)
        self.assertEqual(result.status, LookupStatus.PENDING_EBAY_QUOTA)

    def test_best_offer_remains_weaker(self) -> None:
        row = {
            "item_id": "307126788012", "title": "Umbreon VMAX 215/203 PSA 10",
            "sale_price": 4585.58, "currency": "$", "date_sold": "Aug 14, 2026",
            "buying_format": "Best Offer", "link": "https://www.ebay.com/itm/307126788012",
        }
        obs = normalize_sale_row(row, marketplace="US")
        self.assertIsNotNone(obs)
        self.assertEqual(obs.price_confidence, PriceConfidence.WEAK_BEST_OFFER_EXACT_PRICE)

    def test_auction_is_strong_provider_reported_not_official_ebay(self) -> None:
        row = {
            "item_id": "1", "title": "Exact card", "sale_price": 100,
            "currency": "$", "date_sold": "Aug 14, 2026", "buying_format": "Auction",
        }
        obs = normalize_sale_row(row, marketplace="US")
        self.assertEqual(obs.price_confidence, PriceConfidence.STRONG_PROVIDER_REPORTED)

    def test_global_dedup_keeps_us_uk_as_one_event(self) -> None:
        base = {"item_id": "123", "title": "Exact card", "date_sold": "Aug 14, 2026", "buying_format": "Auction"}
        us = normalize_sale_row({**base, "sale_price": 100, "currency": "$"}, marketplace="US")
        uk = normalize_sale_row({**base, "sale_price": 80, "currency": "£"}, marketplace="UK")
        events = dedupe_global([us, uk])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].ebay_item_id, "123")
        self.assertEqual({o.marketplace for o in events[0].observations}, {"US", "UK"})

    def test_quota_miss_telemetry_is_retrospective(self) -> None:
        telemetry = QuotaImpactTelemetry()
        telemetry.record_eligible()
        telemetry.record_quota_block("umbreon|en|psa|10")
        self.assertEqual(telemetry.lookups_blocked_quota, 1)
        self.assertEqual(telemetry.confirmed_missed_due_to_quota, 0)
        telemetry.record_confirmed_miss("umbreon|en|psa|10")
        self.assertEqual(telemetry.confirmed_missed_due_to_quota, 1)
        self.assertEqual(telemetry.pending_identity_keys, [])

    def test_marketplace_is_not_variant_by_itself(self) -> None:
        self.assertTrue(same_english_card_across_marketplaces(identity_equal=True, regional_variant_proven=False))
        self.assertFalse(same_english_card_across_marketplaces(identity_equal=True, regional_variant_proven=True))


if __name__ == "__main__":
    unittest.main()
