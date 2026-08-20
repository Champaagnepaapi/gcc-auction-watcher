from __future__ import annotations

import unittest

import v4_global_marketplace_notify as runner
from v4_global_market_core import ACTIVE_AUCTION, FIXED_ASK


def _report(gcc=None, evidence=FIXED_ASK):
    decision = {
        "status": "MULTIMARKET_CONFIRMED",
        "would_notify": True,
        "best_market": "fanatics",
        "source_url": "https://market.invalid/1",
        "offer_all_in_eur": 60.0,
        "gcc_fair_eur": gcc,
        "external_fair_eur": 100.0,
        "confirmed_fair_eur": 100.0 if gcc is None else min(float(gcc), 100.0),
        "discount_pct": 40.0,
        "external_provider": "PokemonPriceTracker",
        "external_sales_count": 20,
        "valuation_basis": "EXTERNAL_ONLY" if gcc is None else "GCC_PLUS_EXTERNAL",
        "ask_is_sold": False,
    }
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
                        "all_in_eur": 60.0,
                    }
                ],
                "economic_confirmation": {"decision": decision},
            }
        ]
    }


class MarketplaceNotifyTests(unittest.TestCase):
    def test_external_only_candidate_is_notification_eligible(self):
        self.assertEqual(len(runner.marketplace_notification_candidates(_report())), 1)

    def test_active_auction_is_never_candidate(self):
        self.assertEqual(runner.marketplace_notification_candidates(_report(evidence=ACTIVE_AUCTION)), [])

    def test_formatter_labels_missing_gcc_without_fabricating_sale(self):
        card, decision, offer = runner.marketplace_notification_candidates(_report())[0]
        title, body = runner._format_notification(card, decision, offer)
        self.assertIn("GLOBAL EDGE CONFIRMÉ", title)
        self.assertIn("GCC SOLD fair: absent", body)
        self.assertIn("PAS UNE VENTE", body)
        self.assertIn("Vérification manuelle uniquement", body)

    def test_retry_provider_states_keep_pending(self):
        card = {
            "economic_confirmation": {
                "external_canonical": {"status": "EXACT"},
                "ppt": {"status": "PENDING_BUDGET"},
                "poketrace": {"status": "TRANSIENT_UNAVAILABLE"},
            }
        }
        self.assertFalse(runner._evaluation_complete(card))

    def test_clean_no_match_is_terminal_until_listing_changes(self):
        card = {
            "economic_confirmation": {
                "external_canonical": {"status": "EXACT"},
                "ppt": {"status": "CLEAN_NO_MATCH"},
                "poketrace": {"status": "UNAVAILABLE"},
            }
        }
        self.assertTrue(runner._evaluation_complete(card))


if __name__ == "__main__":
    unittest.main()
