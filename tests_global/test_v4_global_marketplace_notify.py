from __future__ import annotations

import unittest

import v4_global_marketplace_notify as runner
from v4_global_market_core import ACTIVE_AUCTION, FIXED_ASK


def _report(evidence=FIXED_ASK, *, guide=False):
    decision = {
        "status": "MULTIMARKET_CONFIRMED",
        "would_notify": True,
        "best_market": "fanatics",
        "source_url": "https://market.invalid/1",
        "offer_all_in_eur": 55.0 if guide else 60.0,
        "gcc_fair_eur": 25.0,
        "external_fair_eur": 100.0,
        "confirmed_fair_eur": 100.0,
        "discount_pct": 45.0 if guide else 40.0,
        "external_provider": "PriceCharting guide" if guide else "PokemonPriceTracker",
        "external_sales_count": 0 if guide else 20,
        "valuation_basis": "PRICECHARTING_GUIDE_ONLY" if guide else "EXTERNAL_ONLY",
        "valuation_evidence_type": "PRICE_GUIDE" if guide else "SOLD_AGGREGATE",
        "required_discount_pct": 40.0 if guide else 30.0,
        "marketplace_listing_is_valuation": False,
        "marketplace_sources_are_opportunity_only": True,
        "gcc_history_economic_authority": False,
        "ask_is_sold": False,
    }
    price = decision["offer_all_in_eur"]
    return {
        "cards": [
            {
                "identity": {
                    "name": "Mewtwo",
                    "set_name": "151",
                    "number": "183/165",
                    "language": "ja",
                    "grader": "PSA",
                    "grade": "10",
                },
                "offers": [
                    {
                        "market": "fanatics",
                        "evidence_type": evidence,
                        "source_url": "https://market.invalid/1",
                        "all_in_eur": price,
                    }
                ],
                "economic_confirmation": {"decision": decision},
            }
        ]
    }


class MarketplaceNotifyTests(unittest.TestCase):
    def test_external_only_candidate_is_notification_eligible(self):
        self.assertEqual(len(runner.marketplace_notification_candidates(_report())), 1)

    def test_pricecharting_guide_candidate_is_eligible_without_fake_sales(self):
        candidates = runner.marketplace_notification_candidates(_report(guide=True))
        self.assertEqual(len(candidates), 1)
        _card, decision, _offer = candidates[0]
        self.assertEqual(decision["external_sales_count"], 0)
        self.assertEqual(decision["valuation_evidence_type"], "PRICE_GUIDE")

    def test_pricecharting_guide_requires_40_percent_threshold(self):
        report = _report(guide=True)
        decision = report["cards"][0]["economic_confirmation"]["decision"]
        decision["required_discount_pct"] = 30.0
        self.assertEqual(runner.marketplace_notification_candidates(report), [])

    def test_active_auction_is_never_candidate(self):
        self.assertEqual(
            runner.marketplace_notification_candidates(_report(evidence=ACTIVE_AUCTION)),
            [],
        )

    def test_formatter_does_not_use_gcc_history_as_fair_value(self):
        card, decision, offer = runner.marketplace_notification_candidates(_report())[0]
        title, body = runner._format_notification(card, decision, offer)
        self.assertIn("GLOBAL EDGE CONFIRMÉ", title)
        self.assertIn("Fair externe", body)
        self.assertNotIn("GCC SOLD fair", body)
        self.assertIn("prix du vault", body)
        self.assertIn("PAS UNE VENTE", body)
        self.assertIn("Vérification manuelle uniquement", body)

    def test_formatter_labels_pricecharting_as_guide_not_sold(self):
        card, decision, offer = runner.marketplace_notification_candidates(_report(guide=True))[0]
        _title, body = runner._format_notification(card, decision, offer)
        self.assertIn("guide PSA 10 exact", body)
        self.assertIn("pas un SOLD item-level", body)

    def test_retry_provider_states_keep_pending(self):
        card = {
            "economic_confirmation": {
                "external_canonical": {"status": "EXACT"},
                "ppt": {"status": "PENDING_BUDGET"},
                "poketrace": {"status": "TRANSIENT_UNAVAILABLE"},
                "pricecharting": {"status": "UNAVAILABLE"},
            }
        }
        self.assertFalse(runner._evaluation_complete(card))

    def test_clean_no_match_does_not_hide_retryable_sibling(self):
        card = {
            "economic_confirmation": {
                "external_canonical": {"status": "EXACT"},
                "ppt": {"status": "CLEAN_NO_MATCH"},
                "poketrace": {"status": "UNAVAILABLE"},
                "pricecharting": {"status": "UNAVAILABLE"},
            }
        }
        self.assertFalse(runner._evaluation_complete(card))

    def test_all_clean_no_match_are_terminal_until_listing_changes(self):
        card = {
            "economic_confirmation": {
                "external_canonical": {"status": "EXACT"},
                "ppt": {"status": "CLEAN_NO_MATCH"},
                "poketrace": {"status": "CLEAN_NO_MATCH"},
                "pricecharting": {"status": "CLEAN_NO_MATCH"},
            }
        }
        self.assertTrue(runner._evaluation_complete(card))

    def test_confirmed_decision_is_terminal_even_if_unused_provider_retryable(self):
        card = {
            "economic_confirmation": {
                "external_canonical": {"status": "EXACT"},
                "ppt": {"status": "MATCHED"},
                "poketrace": {"status": "UNAVAILABLE"},
                "pricecharting": {"status": "NOT_NEEDED"},
                "decision": {"status": "MULTIMARKET_CONFIRMED"},
            }
        }
        self.assertTrue(runner._evaluation_complete(card))


if __name__ == "__main__":
    unittest.main()
