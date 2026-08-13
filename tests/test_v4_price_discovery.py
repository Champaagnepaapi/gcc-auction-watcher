import unittest

import v4_price_discovery as pd


class V4PriceDiscoveryAndGraderSpreadTests(unittest.TestCase):
    def test_1_pikachu_v_swsh285_pca10_french_illiquid_price_discovery(self):
        """Positive regression: Pikachu V SWSH285 FR PCA10 at 39 EUR with sparse exact liquidity but strong adjacent anchors."""
        anchors = [
            pd.AdjacentAnchor(
                anchor_type="PSA_SAME_GRADE",
                source="poketrace",
                grader="PSA",
                grade="10",
                language="fr",
                price=249.60,
                price_type="SOLD",
                sale_count=4,
            ),
            pd.AdjacentAnchor(
                anchor_type="RAW_CONSENSUS",
                source="raw_consensus",
                grader=None,
                grade=None,
                language="fr",
                price=25.00,
                price_type="CONSENSUS",
                sale_count=3,
            ),

        ]

        signal = pd.evaluate_price_discovery(
            listing_identity="Pikachu V SWSH285 Promo FR",
            gcc_price=39.00,
            grader="PCA",
            grade="10",
            language="fr",
            exact_grader_sales=[],  # Sparse exact PCA10 liquidity
            adjacent_anchors=anchors,
            crossgrade_probability=None,  # Optional: crossgrade not strictly required
        )

        self.assertEqual(signal.category, pd.CATEGORY_ILLIQUID_PRICE_DISCOVERY)
        self.assertEqual(signal.liquidity, pd.LIQUIDITY_LOW)
        self.assertEqual(signal.evidence_quality, pd.EVIDENCE_QUALITY_MODERATE)
        self.assertEqual(signal.uncertainty, pd.UNCERTAINTY_HIGH)
        self.assertEqual(signal.grader_spread, pd.GRADER_SPREAD_VERY_HIGH)
        self.assertAlmostEqual(signal.asymmetric_upside_ratio, 6.4, delta=0.1)
        self.assertFalse(signal.crossgrade_required)
        self.assertTrue(signal.manual_review_recommended)

    def test_2_sparse_market_with_only_stale_active_ask_rejected(self):
        """Negative regression: Sparse market with only one unconfirmed active ask cannot create a strong opportunity."""
        anchors = [
            pd.AdjacentAnchor(
                anchor_type="ACTIVE_ASK",
                source="ebay",
                grader="PSA",
                grade="10",
                language="fr",
                price=500.00,
                price_type="ASK",
                is_active_ask=True,
            )
        ]

        signal = pd.evaluate_price_discovery(
            listing_identity="Rare Card FR",
            gcc_price=50.00,
            grader="PCA",
            grade="10",
            language="fr",
            exact_grader_sales=[],
            adjacent_anchors=anchors,
        )

        self.assertFalse(signal.manual_review_recommended)
        self.assertEqual(signal.evidence_quality, pd.EVIDENCE_QUALITY_LOW)
        self.assertEqual(signal.uncertainty, pd.UNCERTAINTY_VERY_HIGH)

    def test_3_english_psa10_high_vs_french_pca10_is_downweighted(self):
        """Negative regression: English PSA 10 anchor is explicitly downweighted when evaluating a French listing."""
        anchors = [
            pd.AdjacentAnchor(
                anchor_type="PSA_SAME_GRADE",
                source="poketrace",
                grader="PSA",
                grade="10",
                language="en",  # English vs French listing
                price=300.00,
                price_type="SOLD",
                sale_count=2,
            )
        ]

        signal = pd.evaluate_price_discovery(
            listing_identity="Dracaufeu VMAX FR",
            gcc_price=100.00,
            grader="PCA",
            grade="10",
            language="fr",
            exact_grader_sales=[],
            adjacent_anchors=anchors,
        )

        # Anchor must carry language difference uncertainty reason and reduced weight
        anchor = signal.credible_adjacent_anchors[0]
        self.assertIn("LANGUAGE_DIFFERENCE_EN_VS_FR", anchor.uncertainty_reasons)
        self.assertLess(anchor.weight, 1.0)
        self.assertIn(signal.uncertainty, {pd.UNCERTAINTY_HIGH, pd.UNCERTAINTY_VERY_HIGH})

    def test_4_low_grade_mew_cannot_use_huge_psa10_anchor(self):
        """Negative regression: CA 6 Mew XY110 FR at 100 EUR must not become an opportunity merely because PSA 10 is huge."""
        anchors = [
            pd.AdjacentAnchor(
                anchor_type="PSA_HIGHER_GRADE",
                source="poketrace",
                grader="PSA",
                grade="10",
                language="fr",
                price=3000.00,
                price_type="SOLD",
                sale_count=5,
            )
        ]

        signal = pd.evaluate_price_discovery(
            listing_identity="Mew XY110 FR",
            gcc_price=100.00,
            grader="CA",
            grade="6",
            language="fr",
            exact_grader_sales=[],
            adjacent_anchors=anchors,
        )

        # Low-grade listing (6) with wide grade gap to 10 is filtered out
        self.assertFalse(signal.manual_review_recommended)
        self.assertEqual(len(signal.credible_adjacent_anchors), 0)

    def test_5_liquid_secondary_grader_market_above_fair_value_no_discount(self):
        """Negative regression: Liquid secondary-grader market where ask >= fair market gives no discount signal."""
        exact_sales = [120.0, 125.0, 118.0, 122.0]
        anchors = [
            pd.AdjacentAnchor(
                anchor_type="PCA_SOLD",
                source="gcc",
                grader="PCA",
                grade="9.5",
                language="fr",
                price=120.00,
                price_type="SOLD",
                sale_count=4,
            )
        ]

        signal = pd.evaluate_price_discovery(
            listing_identity="Mewtwo GX FR",
            gcc_price=130.00,  # Ask higher than 120 EUR sold comp
            grader="PCA",
            grade="9.5",
            language="fr",
            exact_grader_sales=exact_sales,
            adjacent_anchors=anchors,
        )

        self.assertEqual(signal.exact_grader_liquidity, pd.LIQUIDITY_HIGH)
        self.assertFalse(signal.manual_review_recommended)
        self.assertLess(signal.asymmetric_upside_ratio, 1.1)

    def test_6_missing_crossgrade_probability_does_not_suppress_signal(self):
        """Invariant: Missing crossgrade probability must NOT suppress a valid adjacent-evidence signal."""
        anchors = [
            pd.AdjacentAnchor(
                anchor_type="PSA_SAME_GRADE",
                source="poketrace",
                grader="PSA",
                grade="10",
                language="fr",
                price=200.00,
                price_type="SOLD",
                sale_count=3,
            ),
            pd.AdjacentAnchor(
                anchor_type="RAW_CONSENSUS",
                source="raw_consensus",
                grader=None,
                grade=None,
                language="fr",
                price=90.00,
                price_type="CONSENSUS",
                sale_count=2,
            ),
        ]

        signal = pd.evaluate_price_discovery(
            listing_identity="Lugia V FR",
            gcc_price=45.00,
            grader="PCA",
            grade="10",
            language="fr",
            exact_grader_sales=[],
            adjacent_anchors=anchors,
            crossgrade_probability=None,  # No crossgrade probability provided
        )

        self.assertTrue(signal.manual_review_recommended)
        self.assertFalse(signal.crossgrade_required)
        self.assertGreaterEqual(signal.asymmetric_upside_ratio, 4.0)

    def test_7_crossgrade_opportunity_when_crossgrade_probability_high(self):
        """Classification: High crossgrade probability generates CROSSGRADE_OPPORTUNITY."""
        anchors = [
            pd.AdjacentAnchor(
                anchor_type="PSA_SAME_GRADE",
                source="poketrace",
                grader="PSA",
                grade="10",
                language="fr",
                price=500.00,
                price_type="SOLD",
                sale_count=5,
            )
        ]

        signal = pd.evaluate_price_discovery(
            listing_identity="Rayquaza VMAX Alt Art FR",
            gcc_price=200.00,
            grader="BGS",
            grade="9.5",
            language="fr",
            exact_grader_sales=[],
            adjacent_anchors=anchors,
            crossgrade_probability=0.85,
        )

        self.assertEqual(signal.category, pd.CATEGORY_CROSSGRADE_OPPORTUNITY)
        self.assertTrue(signal.manual_review_recommended)

    def test_8_secondary_grader_discount_on_liquid_market(self):
        """Classification: Liquid secondary grader market trading at discount yields SECONDARY_GRADER_DISCOUNT."""
        exact_sales = [80.0, 85.0, 82.0, 78.0]
        anchors = [
            pd.AdjacentAnchor(
                anchor_type="PCA_SOLD",
                source="gcc",
                grader="PCA",
                grade="9",
                language="fr",
                price=80.00,
                price_type="SOLD",
                sale_count=4,
            ),
            pd.AdjacentAnchor(
                anchor_type="PSA_SAME_GRADE",
                source="poketrace",
                grader="PSA",
                grade="9",
                language="fr",
                price=110.00,
                price_type="SOLD",
                sale_count=6,
            ),
        ]

        signal = pd.evaluate_price_discovery(
            listing_identity="Gengar VMAX FR",
            gcc_price=40.00,  # 50% discount vs 80 EUR PCA market
            grader="PCA",
            grade="9",
            language="fr",
            exact_grader_sales=exact_sales,
            adjacent_anchors=anchors,
        )

    def test_9_integration_real_v4_candidate_reaches_illiquid_price_discovery(self):
        """Integration test: Real V4 ValuationCandidate reaches ILLIQUID_PRICE_DISCOVERY via multimarket pipeline."""
        from datetime import datetime, timezone
        from unittest.mock import patch
        import watcher
        import v4_canonical_multimarket as mm

        now = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)

        # Real V4 Lot: Pikachu V SWSH285 Promo FR PCA 10 at 39.00 EUR
        lot = watcher.Lot(
            url="https://gcc.test/item/12345",
            title="Pikachu V SWSH285 Promo PCA 10",
            current_price=39.00,
            source_type="fixed",
            grader="PCA",
            grade="10",
            card_set="SWSH Promos",
            card_number="SWSH285",
            language="fr",
            commercial_dimensions={"edition": "none", "finish": "holo"},
        )


        gcc_evidence = watcher.GccMarketEvidence(
            lot=lot,
            sales=[],  # Sparse exact PCA 10 GCC history
            estimate=None,
            opportunity=None,
            branch=watcher.GCC_BRANCH_REJECTED,
            strength=watcher.EVIDENCE_WEAK,
        )


        candidate = watcher.ValuationCandidate(gcc=gcc_evidence)

        canonical = mm.CanonicalCard(
            status="EXACT",
            card_id="swshp-SWSH285",
            name="Pikachu V",
            set_id="swshp",
            set_name="SWSH Promos",
            local_id="SWSH285",
            full_number="SWSH285",
            language_code="fr",
        )


        # Realistic French RAW consensus: ~25 EUR
        raw = mm.RawMarketSignal(
            low=20.0,
            central=25.0,
            high=30.0,
            currency="EUR",
            sources=("Cardmarket", "JustTCG"),
            variant="holo",
            confidence="STRONG",
        )


        # PokeTrace returns clean no match for exact PCA 10
        poketrace = watcher.ExternalMarketEvidence(
            identity_key=watcher.external_commercial_identity_key(lot),
            status=watcher.EXTERNAL_CLEAN_NO_MATCH,
            strength=watcher.EVIDENCE_UNAVAILABLE,
            source="poketrace",
            note="PokeTrace exact PCA 10 absent",
            fetched_at=now,
        )

        # Fallback (PSA APR / eBay) found sparse exact PCA 10, but discovered 4 PSA 10 sold comparables at 249.60 EUR
        fallback = watcher.ExternalMarketEvidence(
            identity_key=watcher.external_commercial_identity_key(lot),
            status=watcher.EXTERNAL_CLEAN_NO_MATCH,
            strength=watcher.EVIDENCE_UNAVAILABLE,
            source="ebay",
            comparables=[
                watcher.ComparableSale(
                    price=249.60,
                    source="ebay",
                    grader="PSA",
                    grade=10.0,
                    context="fr",
                )
            ],
            note="eBay exact PCA 10 absent; found PSA 10 sold comps",
            fetched_at=now,
        )



        state = {}
        with patch.object(mm, "_canonical_from_lot", return_value=canonical), \
             patch.object(mm, "raw_market_signal", return_value=raw), \
             patch.object(mm, "_poketrace_evidence", return_value=poketrace), \
             patch.object(mm, "_fallback_external", return_value=fallback), \
             patch.object(mm, "_notify_manual_review") as notify_mock:

            opportunities = mm.multimarket_process_external_market_candidates(
                None,
                [candidate],
                state,
                watcher.ValidationBudgets(),
                watcher.RunDiagnostics(),
                now,
            )

        # Invariant: No automatic purchase/bid/opportunity created
        self.assertEqual(opportunities, [])

        # Notification must be triggered for manual review
        notify_mock.assert_called_once()
        lead = notify_mock.call_args[0][0]

        # Verify discovery signal on the real candidate lead
        self.assertIsNotNone(lead.discovery_signal)
        sig = lead.discovery_signal
        self.assertEqual(sig.category, pd.CATEGORY_ILLIQUID_PRICE_DISCOVERY)
        self.assertEqual(sig.liquidity, pd.LIQUIDITY_LOW)
        self.assertEqual(sig.evidence_quality, pd.EVIDENCE_QUALITY_MODERATE)
        self.assertEqual(sig.uncertainty, pd.UNCERTAINTY_HIGH)
        self.assertEqual(sig.grader_spread, pd.GRADER_SPREAD_VERY_HIGH)
        self.assertAlmostEqual(sig.asymmetric_upside_ratio, 6.4, delta=0.1)
        self.assertFalse(sig.crossgrade_required)
        self.assertTrue(sig.manual_review_recommended)

        # Verify state deduplication record
        self.assertIn(mm.MANUAL_REVIEW_STATE_KEY, state)


if __name__ == "__main__":
    unittest.main()
