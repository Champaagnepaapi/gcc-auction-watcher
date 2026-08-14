from __future__ import annotations

import unittest
from types import SimpleNamespace

import watcher
import v4_canonical_multimarket as canonical_market
import v4_edge_hunter_safety as safety
import v4_price_discovery as price_discovery


class EdgeHunterSafetyTests(unittest.TestCase):
    def test_language_aliases_collapse_to_same_code(self):
        for value in ("French", "FR", "fr", "français", "Francais", "FRA", "fr-FR"):
            with self.subTest(value=value):
                self.assertEqual(safety.canonical_language_code(value), "fr")

    def test_canonical_identity_requires_resolved_card_key(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/example",
            title="Dracaufeu",
            current_price=46.0,
            source_type="fixed",
            grader="PCA",
            grade="10",
            card_number="4/102",
            language="French",
        )
        incomplete = canonical_market.CanonicalCard(status="NO_MATCH")
        self.assertFalse(safety.canonical_identity_complete(lot, incomplete))

        exact = canonical_market.CanonicalCard(
            status="EXACT",
            card_id="base1-4",
            set_id="base1",
            set_name="Base Set",
            local_id="4",
            full_number="4/102",
            name="Charizard",
            language_code="fr",
        )
        self.assertTrue(safety.canonical_identity_complete(lot, exact))

    def test_french_vs_fr_has_no_language_penalty_and_same_grader_is_relabelled(self):
        sales = [
            SimpleNamespace(
                grader="PCA",
                grade=10.0,
                sold_at=None,
                age_days=10,
            )
            for _ in range(4)
        ]
        anchors = tuple(
            price_discovery.AdjacentAnchor(
                anchor_type="EXACT_GCC_SOLD",
                source="gcc",
                grader="PCA",
                grade="10",
                language="French",
                price=price,
                price_type="SOLD",
                age_days=10,
                is_recent=True,
            )
            for price in (65.0, 70.0, 70.0, 75.0)
        )

        signal = safety.evaluate_price_discovery_guarded(
            listing_identity="Charizard #4/102",
            gcc_price=46.0,
            grader="PCA",
            grade="10",
            language="FR",
            target_language="FR",
            exact_grader_sales=sales,
            recent_exact_sales=sales,
            adjacent_anchors=anchors,
        )

        self.assertEqual(signal.category, safety.CATEGORY_SAME_GRADER_MARKET_DISCOUNT)
        self.assertAlmostEqual(signal.credible_high_reference, 70.0)
        self.assertGreater(signal.asymmetric_upside_ratio, 1.5)
        reasons = {
            reason
            for anchor in signal.credible_adjacent_anchors
            for reason in anchor.uncertainty_reasons
        }
        self.assertFalse(any(reason.startswith("LANGUAGE_DIFFERENCE_") for reason in reasons))

    def test_coverage_message_never_uses_wider_auction_total_as_denominator(self):
        diagnostics = watcher.RunDiagnostics()
        diagnostics.fixed_coverage.listing_ids = {f"fixed-{i}" for i in range(3023)}
        diagnostics.fixed_coverage.expected_total = 3023
        diagnostics.fixed_coverage.expected_total_scope = watcher.EXPECTED_TOTAL_SAME_QUERY
        diagnostics.fixed_coverage.pagination_end_reason = watcher.END_DECLARED_TOTAL_REACHED

        diagnostics.auction_coverage.listing_ids = {f"auction-{i}" for i in range(133)}
        diagnostics.auction_coverage.expected_total = 14568
        diagnostics.auction_coverage.expected_total_scope = watcher.EXPECTED_TOTAL_DIFFERENT_SCOPE
        diagnostics.auction_coverage.mark_incomplete(
            "synthetic target-scope failure",
            watcher.END_MALFORMED_RESPONSE,
        )
        setattr(
            diagnostics,
            "auction_discovery_scope_status",
            "TARGET_SCOPE_INCOMPLETE",
        )

        message = safety.format_technical_coverage_message(diagnostics)
        self.assertIn("Discovery auctions target scope: 133 listing(s) observed", message)
        self.assertIn(
            "GCC wider on-sale auction total (diagnostic only; not denominator): 14568",
            message,
        )
        self.assertNotIn("133/14568", message)
        self.assertIn("GLOBAL COVERAGE: INCOMPLETE", message)
        self.assertIn(
            "Discovery itself is not capped by valuation/provider budgets.",
            message,
        )


if __name__ == "__main__":
    unittest.main()
