from __future__ import annotations

import unittest

from v5.ebay_asp_basic_policy import (
    CandidateContext,
    LookupStatus,
    PriceConfidence,
    QuotaImpactTelemetry,
    choose_lookup,
    classify_sale_price,
    dedupe_sales_global,
    same_english_card_across_marketplaces,
)


class EbayAspBasicPolicyTests(unittest.TestCase):
    def test_requires_exact_identity_and_interesting_candidate(self) -> None:
        self.assertEqual(
            choose_lookup(CandidateContext(False, True), remaining_requests=50).status,
            LookupStatus.NOT_ELIGIBLE,
        )
        self.assertEqual(
            choose_lookup(CandidateContext(True, False), remaining_requests=50).status,
            LookupStatus.NOT_ELIGIBLE,
        )

    def test_uses_cache_before_spending_quota(self) -> None:
        decision = choose_lookup(
            CandidateContext(True, True, cached_strong_sold=3),
            remaining_requests=50,
        )
        self.assertEqual(decision.status, LookupStatus.CACHE_SUFFICIENT)

    def test_us_first_then_uk_only_if_us_has_fewer_than_three_strong_sales(self) -> None:
        candidate = CandidateContext(True, True)
        self.assertEqual(choose_lookup(candidate, remaining_requests=10).status, LookupStatus.QUERY_US)
        self.assertEqual(
            choose_lookup(candidate, remaining_requests=9, us_strong_sold=2).status,
            LookupStatus.QUERY_UK_FALLBACK,
        )
        self.assertEqual(
            choose_lookup(candidate, remaining_requests=9, us_strong_sold=3).status,
            LookupStatus.CACHE_SUFFICIENT,
        )

    def test_quota_exhaustion_is_pending_not_negative(self) -> None:
        decision = choose_lookup(CandidateContext(True, True), remaining_requests=0)
        self.assertEqual(decision.status, LookupStatus.PENDING_EBAY_QUOTA)
        self.assertEqual(decision.reason, "EBAY_ASP_QUOTA_EXHAUSTED")

    def test_best_offer_price_is_not_strong_exact_price(self) -> None:
        self.assertEqual(
            classify_sale_price({"buying_format": "Best Offer"}),
            PriceConfidence.WEAK_EXACT_PRICE,
        )
        self.assertEqual(classify_sale_price({"buying_format": "Auction"}), PriceConfidence.STRONG)
        self.assertEqual(classify_sale_price({"buying_format": "Buy It Now"}), PriceConfidence.STRONG)

    def test_global_item_id_dedup_preserves_us_uk_provenance(self) -> None:
        rows = [
            {
                "item_id": "123",
                "site": "US",
                "currency": "$",
                "link": "https://www.ebay.com/itm/123",
                "price": 100,
            },
            {
                "item_id": "123",
                "site": "UK",
                "currency": "£",
                "link": "https://www.ebay.co.uk/itm/123",
                "price": 80,
            },
        ]
        deduped = dedupe_sales_global(rows)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["ebay_item_id"], "123")
        self.assertEqual(set(deduped[0]["marketplaces_seen"]), {"US", "UK"})
        self.assertEqual(set(deduped[0]["currencies_seen"]), {"$", "£"})

    def test_marketplace_does_not_create_variant_by_itself(self) -> None:
        self.assertTrue(same_english_card_across_marketplaces(identity_equal=True, regional_variant_proven=False))
        self.assertFalse(same_english_card_across_marketplaces(identity_equal=True, regional_variant_proven=True))
        self.assertFalse(same_english_card_across_marketplaces(identity_equal=False, regional_variant_proven=False))

    def test_quota_impact_is_measurable_and_replayable(self) -> None:
        metrics = QuotaImpactTelemetry()
        metrics.record_eligible()
        metrics.record_quota_block("umbreon|swsh7|215|EN|PSA|10")
        self.assertEqual(metrics.eligible_candidates, 1)
        self.assertEqual(metrics.lookups_blocked_quota, 1)
        self.assertEqual(len(metrics.pending_identity_keys), 1)
        metrics.record_confirmed_miss("umbreon|swsh7|215|EN|PSA|10")
        self.assertEqual(metrics.confirmed_missed_due_to_quota, 1)
        self.assertEqual(metrics.pending_identity_keys, [])


if __name__ == "__main__":
    unittest.main()
