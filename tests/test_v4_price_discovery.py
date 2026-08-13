import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import v4_canonical_multimarket as mm
import v4_price_discovery as pd
import watcher


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
        self.assertFalse(signal.manual_review_recommended)


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


class TemporalCrossGraderAdjustmentTests(unittest.TestCase):
    """
    Test suite for TEMPORAL_CROSS_GRADER_ADJUSTMENT:
    - Rebasing old secondary-grader sales with broader market appreciation.
    - Outlier rejection across multiple observations.
    - Uncertainty and confidence downweighting on language mismatch and market volatility.
    - Clean fail-closed behavior when no usable historical ratio/reference is present.
    - Recent exact sales overriding temporal adjustment.
    """

    def test_1_rayquaza_xy141_sgs8_temporal_cross_grader_adjustment(self):
        """
        Rayquaza XY141 SGS 8 at 39 EUR:
        - Old SGS 8 sale = 18 EUR (250 days ago)
        - Historical PSA 8 benchmark at that time = 30 EUR -> historical ratio = 0.60
        - Current robust PSA 8 market value = 100 EUR
        => Old SGS 8 sale is rebased to 60 EUR (range 51-69 EUR) rather than treating 18 EUR as today's value.
        => Implicit discount vs GCC price 39 EUR is 35.0%.
        => is_extrapolated = True, manual review recommended.
        """
        historical_sgs = [
            pd.HistoricalRatioObservation(
                target_grader_price=18.0,
                reference_grader_price=30.0,
                ratio=0.60,
                age_days=250,
                target_grader="SGS",
                reference_grader="PSA",
                grade="8",
                language="fr",
                reference_language="fr",
            )
        ]

        res = pd.evaluate_temporal_cross_grader_adjustment(
            target_grader="SGS",
            target_grade="8",
            gcc_price=39.0,
            historical_target_sales=historical_sgs,
            current_robust_reference_value=100.0,
            reference_grader="PSA",
            target_language="fr",
            reference_language="fr",
        )

        self.assertTrue(res.applied)
        self.assertTrue(res.is_extrapolated)
        self.assertEqual(res.extrapolation_type, pd.EXTRAPOLATION_TEMPORAL_CROSS_GRADER)
        self.assertEqual(res.evidence_level, pd.EVIDENCE_LEVEL_TEMPORALLY_ADJUSTED)
        self.assertEqual(res.historical_exact_grader_sale, 18.0)
        self.assertEqual(res.historical_reference_price, 30.0)
        self.assertEqual(res.historical_grader_reference_ratio, 0.60)
        self.assertEqual(res.current_robust_reference_value, 100.0)
        self.assertEqual(res.temporally_adjusted_central, 60.0)
        self.assertEqual(res.temporally_adjusted_low, 51.0)
        self.assertEqual(res.temporally_adjusted_high, 69.0)
        self.assertAlmostEqual(res.implicit_discount_pct, 35.0, delta=0.1)

        # Signal integration check
        signal = pd.evaluate_price_discovery(
            listing_identity="rayquaza_xy141_sgs8_fr",
            gcc_price=39.0,
            grader="SGS",
            grade="8",
            language="fr",
            temporal_adjustment=res,
            adjacent_anchors=(
                pd.AdjacentAnchor(
                    anchor_type="PSA_SAME_GRADE",
                    source="poketrace",
                    grader="PSA",
                    grade="8",
                    language="fr",
                    price=100.0,
                    price_type="SOLD",
                    sale_count=4,
                ),
            ),
        )

        self.assertTrue(signal.is_extrapolated)
        self.assertEqual(signal.extrapolation_type, pd.EXTRAPOLATION_TEMPORAL_CROSS_GRADER)
        self.assertEqual(signal.evidence_level, pd.EVIDENCE_LEVEL_TEMPORALLY_ADJUSTED)
        self.assertEqual(signal.temporally_adjusted_central, 60.0)
        self.assertTrue(signal.manual_review_recommended)
        self.assertIn("temporally rebased", signal.main_thesis)

    def test_2_anomalous_outlier_ratio_does_not_dominate(self):
        """
        Multiple historical ratio observations with one huge outlier (e.g. 2.0 vs 0.60):
        The robust median ensures the outlier does not distort the central estimate.
        """
        historical_obs = [
            pd.HistoricalRatioObservation(18.0, 30.0, 0.60, age_days=200, target_grader="SGS"),
            pd.HistoricalRatioObservation(17.5, 30.0, 0.5833, age_days=210, target_grader="SGS"),
            pd.HistoricalRatioObservation(18.5, 30.0, 0.6167, age_days=190, target_grader="SGS"),
            pd.HistoricalRatioObservation(60.0, 30.0, 2.00, age_days=220, target_grader="SGS"),  # anomalous outlier
        ]

        res = pd.evaluate_temporal_cross_grader_adjustment(
            target_grader="SGS",
            target_grade="8",
            gcc_price=39.0,
            historical_target_sales=historical_obs,
            current_robust_reference_value=100.0,
            reference_grader="PSA",
        )

        self.assertTrue(res.applied)
        # Robust ratio should remain ~0.60, not pulled towards 1.0+
        self.assertAlmostEqual(res.historical_grader_reference_ratio, 0.60, delta=0.03)
        self.assertAlmostEqual(res.temporally_adjusted_central, 60.0, delta=3.0)

    def test_3_language_mismatch_increases_uncertainty(self):
        """
        French SGS 8 paired with English PSA 8 reference:
        Language mismatch must be flagged and increase uncertainty.
        """
        historical_obs = [
            pd.HistoricalRatioObservation(
                18.0, 30.0, 0.60, age_days=200, target_grader="SGS", language="fr", reference_language="en"
            )
        ]

        res = pd.evaluate_temporal_cross_grader_adjustment(
            target_grader="SGS",
            target_grade="8",
            gcc_price=39.0,
            historical_target_sales=historical_obs,
            current_robust_reference_value=100.0,
            reference_grader="PSA",
            target_language="fr",
            reference_language="en",
        )

        self.assertTrue(res.applied)
        self.assertIn("CROSS_LANGUAGE_BENCHMARK_FR_VS_EN", res.uncertainty_reasons)
        self.assertIn(res.uncertainty, {pd.UNCERTAINTY_HIGH, pd.UNCERTAINTY_VERY_HIGH})

    def test_4_stale_volatile_reference_market_prevents_strong_confidence(self):
        """
        When the reference market is volatile (high variance), confidence cannot be STRONG.
        """
        historical_obs = [
            pd.HistoricalRatioObservation(18.0, 30.0, 0.60, age_days=200, target_grader="SGS")
        ]

        res = pd.evaluate_temporal_cross_grader_adjustment(
            target_grader="SGS",
            target_grade="8",
            gcc_price=39.0,
            historical_target_sales=historical_obs,
            current_robust_reference_value=100.0,
            reference_volatility="HIGH",
        )

        self.assertTrue(res.applied)
        self.assertNotEqual(res.confidence, pd.EVIDENCE_QUALITY_STRONG)
        self.assertIn("REFERENCE_MARKET_VOLATILITY_HIGH", res.uncertainty_reasons)

    def test_5_no_usable_historical_data_fails_closed_without_invented_estimate(self):
        """
        If there is no usable historical ratio or reference value,
        no estimate is invented and evidence level is MANUAL_REVIEW_NO_ESTIMATE.
        """
        res = pd.evaluate_temporal_cross_grader_adjustment(
            target_grader="SGS",
            target_grade="8",
            gcc_price=39.0,
            historical_target_sales=[],
            current_robust_reference_value=None,
        )

        self.assertFalse(res.applied)
        self.assertFalse(res.is_extrapolated)
        self.assertIsNone(res.temporally_adjusted_central)
        self.assertEqual(res.evidence_level, pd.EVIDENCE_LEVEL_MANUAL_REVIEW_NO_ESTIMATE)
        self.assertEqual(res.uncertainty, pd.UNCERTAINTY_VERY_HIGH)

    def test_6_recent_exact_sales_override_temporal_extrapolation(self):
        """
        Recent exact sales of the target grader (within 90 days) override temporal extrapolation.
        Evidence level is EXACT_RECENT_COMP and is_extrapolated is False.
        """
        recent_sales = [
            type("Comp", (), {"price": 38.0})(),
            type("Comp", (), {"price": 40.0})(),
        ]

        res = pd.evaluate_temporal_cross_grader_adjustment(
            target_grader="SGS",
            target_grade="8",
            gcc_price=39.0,
            historical_target_sales=[
                pd.HistoricalRatioObservation(18.0, 30.0, 0.60, age_days=250)
            ],
            recent_exact_sales=recent_sales,
            current_robust_reference_value=100.0,
        )

        self.assertFalse(res.applied)
        self.assertFalse(res.is_extrapolated)
        self.assertEqual(res.evidence_level, pd.EVIDENCE_LEVEL_EXACT_RECENT)
        self.assertEqual(res.historical_exact_grader_sale, 39.0)
        self.assertIn("RECENT_EXACT_SALES_AVAILABLE", res.uncertainty_reasons)

    def test_7_true_pipeline_integration_real_valuation_candidate_temporal_cross_grader_adjustment(self):
        """
        True pipeline integration test:
        Real ValuationCandidate -> multimarket_process_external_market_candidates / _collect_price_discovery_lead ->
        Old Rayquaza XY141 SGS 8 sale + historical PSA 8 reference comp ->
        Current robust PSA 8 comps ->
        TEMPORAL_CROSS_GRADER_ADJUSTMENT -> manual review.
        """
        now = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
        lot = watcher.Lot(
            url="https://gcc.example/lot/rayquaza_sgs8",
            title="Rayquaza XY141 Promo SGS 8",
            current_price=39.0,
            source_type="fixed",
            grader="SGS",
            grade="8",
            card_set="XY Promos",
            card_number="XY141",
            language="fr",
        )

        # Real GCC sales history:
        # 1. Stale SGS 8 sale (18 €) 250 days ago
        # 2. Historical PSA 8 sale (30 €) 240 days ago (delta = 10 days <= 90 days)
        # 3. Unrelated PCA 9 sale (50 €) 100 days ago
        # 4. Unrelated PSA 10 sale (200 €) 10 days ago
        gcc_sales = [
            watcher.ComparableSale(
                price=18.0,
                grader="SGS",
                grade=8.0,
                sold_at=now - timedelta(days=250),
                exact_card=True,
                source="gcc",
            ),
            watcher.ComparableSale(
                price=30.0,
                grader="PSA",
                grade=8.0,
                sold_at=now - timedelta(days=240),
                exact_card=True,
                source="gcc",
            ),
            watcher.ComparableSale(
                price=50.0,
                grader="PCA",
                grade=9.0,
                sold_at=now - timedelta(days=100),
                exact_card=True,
                source="gcc",
            ),
            watcher.ComparableSale(
                price=200.0,
                grader="PSA",
                grade=10.0,
                sold_at=now - timedelta(days=10),
                exact_card=True,
                source="gcc",
            ),
        ]
        gcc_evidence = watcher.GccMarketEvidence(
            lot=lot,
            sales=gcc_sales,
            estimate=None,
            opportunity=None,
            branch=watcher.GCC_BRANCH_REJECTED,
            strength=watcher.EVIDENCE_WEAK,
        )

        candidate = watcher.ValuationCandidate(gcc=gcc_evidence)
        state = {}

        # Mock TCGdex canonical resolution
        canonical = mm.CanonicalCard(
            status="EXACT",
            card_id="xy-141",
            name="Rayquaza",
            set_id="xy",
            set_name="XY Promos",
            local_id="XY141",
            full_number="XY141",
            language_code="fr",
        )


        # Current external market for PSA 8 around 100 EUR
        poketrace_evidence = watcher.ExternalMarketEvidence(
            identity_key=watcher.external_commercial_identity_key(lot),
            status=watcher.EXTERNAL_MATCHED,
            strength=watcher.EVIDENCE_WEAK,  # Weak exact SGS 8 evidence from PokeTrace
            source="poketrace",
            note="PokeTrace graded",
            fetched_at=now,
            comparables=[
                watcher.ComparableSale(
                    price=98.0,
                    grader="PSA",
                    grade=8.0,
                    sold_at=now - timedelta(days=5),
                    exact_card=True,
                    source="poketrace",
                ),
                watcher.ComparableSale(
                    price=100.0,
                    grader="PSA",
                    grade=8.0,
                    sold_at=now - timedelta(days=12),
                    exact_card=True,
                    source="poketrace",
                ),
                watcher.ComparableSale(
                    price=102.0,
                    grader="PSA",
                    grade=8.0,
                    sold_at=now - timedelta(days=20),
                    exact_card=True,
                    source="poketrace",
                ),
            ],
        )

        with patch("v4_canonical_multimarket._canonical_from_lot", return_value=canonical), \
             patch("v4_canonical_multimarket.raw_market_signal", return_value=None), \
             patch("v4_canonical_multimarket._poketrace_evidence", return_value=poketrace_evidence), \
             patch("v4_canonical_multimarket._fallback_external", return_value=watcher.ExternalMarketEvidence(
                 identity_key=watcher.external_commercial_identity_key(lot),
                 status=watcher.EXTERNAL_CLEAN_NO_MATCH,
                 strength=watcher.EVIDENCE_UNAVAILABLE,
                 source="ebay",
                 fetched_at=now,
             )), \
             patch("v4_canonical_multimarket._notify_manual_review") as notify_mock:

            opportunities = mm.multimarket_process_external_market_candidates(
                None,
                [candidate],
                state,
                watcher.ValidationBudgets(),
                watcher.RunDiagnostics(),
                now,
            )

        # Invariants
        self.assertEqual(opportunities, [])
        notify_mock.assert_called_once()
        lead = notify_mock.call_args[0][0]

        self.assertIsNotNone(lead.discovery_signal)
        sig = lead.discovery_signal

        # Verify temporal extrapolation details
        self.assertTrue(sig.is_extrapolated)
        self.assertEqual(sig.extrapolation_type, pd.EXTRAPOLATION_TEMPORAL_CROSS_GRADER)
        self.assertEqual(sig.evidence_level, pd.EVIDENCE_LEVEL_TEMPORALLY_ADJUSTED)
        self.assertEqual(sig.historical_exact_grader_sale, 18.0)
        self.assertEqual(sig.historical_reference_price, 30.0)
        self.assertAlmostEqual(sig.historical_grader_reference_ratio, 0.60, delta=0.01)
        self.assertAlmostEqual(sig.current_robust_reference_value, 100.0, delta=1.0)
        self.assertAlmostEqual(sig.temporally_adjusted_central, 60.0, delta=1.0)
        self.assertAlmostEqual(sig.implicit_discount_pct, 35.0, delta=1.0)
        self.assertTrue(sig.manual_review_recommended)

    def test_8_mixed_grader_gcc_history_does_not_inflate_exact_sgs_liquidity(self):
        """
        Negative test: A card with 5 PSA 10 GCC sales must NOT count as SGS 8 liquidity.
        Exact SGS 8 liquidity must remain LOW.
        """
        now = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
        lot = watcher.Lot(
            url="https://gcc.example/lot/sgs8_mixed",
            title="SGS 8",
            current_price=50.0,
            source_type="fixed",
            grader="SGS",
            grade="8",
            language="fr",
        )
        gcc_sales = [
            watcher.ComparableSale(price=100.0, grader="PSA", grade=10.0, sold_at=now - timedelta(days=i), exact_card=True)
            for i in range(1, 6)
        ]
        gcc_evidence = watcher.GccMarketEvidence(
            lot=lot,
            sales=gcc_sales,
            estimate=None,
            opportunity=None,
            branch=watcher.GCC_BRANCH_REJECTED,
            strength=watcher.EVIDENCE_WEAK,
        )
        candidate = watcher.ValuationCandidate(gcc=gcc_evidence)
        canonical = mm.CanonicalCard(status="EXACT", card_id="c1", name="Card", set_id="s1", set_name="Set", local_id="1", full_number="1", language_code="fr")

        sig = pd.evaluate_price_discovery(
            listing_identity="SGS 8",
            gcc_price=50.0,
            grader="SGS",
            grade="8",
            exact_grader_sales=gcc_sales,
            language="fr",
            now=now,
        )
        self.assertEqual(sig.exact_grader_liquidity, pd.LIQUIDITY_LOW)
        self.assertEqual(sig.liquidity, pd.LIQUIDITY_LOW)

        # Fail closed: mixed grader history alone without same-grade anchors cannot create lead
        lead = mm._collect_price_discovery_lead(candidate, canonical, raw=None, now=now)
        self.assertIsNone(lead)

    def test_9_mixed_grade_gcc_history_does_not_count_as_exact_liquidity(self):
        """
        Negative test: SGS 9 sales must NOT count as exact SGS 8 liquidity.
        """
        now = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
        lot = watcher.Lot(
            url="https://gcc.example/lot/sgs8_mixed_grades",
            title="SGS 8",
            current_price=50.0,
            source_type="fixed",
            grader="SGS",
            grade="8",
            language="fr",
        )
        gcc_sales = [
            watcher.ComparableSale(price=80.0, grader="SGS", grade=9.0, sold_at=now - timedelta(days=i), exact_card=True)
            for i in range(1, 5)
        ]
        gcc_evidence = watcher.GccMarketEvidence(
            lot=lot,
            sales=gcc_sales,
            estimate=None,
            opportunity=None,
            branch=watcher.GCC_BRANCH_REJECTED,
            strength=watcher.EVIDENCE_WEAK,
        )
        candidate = watcher.ValuationCandidate(gcc=gcc_evidence)
        canonical = mm.CanonicalCard(status="EXACT", card_id="c1", name="Card", set_id="s1", set_name="Set", local_id="1", full_number="1", language_code="fr")

        sig = pd.evaluate_price_discovery(
            listing_identity="SGS 8",
            gcc_price=50.0,
            grader="SGS",
            grade="8",
            exact_grader_sales=gcc_sales,
            language="fr",
            now=now,
        )
        self.assertEqual(sig.exact_grader_liquidity, pd.LIQUIDITY_LOW)

        # Fail closed: mixed grade history alone without same-grade anchors cannot create lead
        lead = mm._collect_price_discovery_lead(candidate, canonical, raw=None, now=now)
        self.assertIsNone(lead)


    def test_10_current_psa_high_without_date_matched_historical_psa_fails_closed(self):
        """
        Negative test: An old SGS 8 sale without a date-matched historical PSA 8 sale
        must NOT use current PSA 8 prices to invent a ratio.
        is_extrapolated must be False, and evidence_level is MANUAL_REVIEW_NO_ESTIMATE.
        """
        now = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
        lot = watcher.Lot(
            url="https://gcc.example/lot/sgs8_fail_closed",
            title="SGS 8",
            current_price=39.0,
            source_type="fixed",
            grader="SGS",
            grade="8",
            language="fr",
        )
        # SGS 8 sold 250 days ago, but NO historical PSA 8 sale existed around that date
        gcc_sales = [
            watcher.ComparableSale(
                price=18.0,
                grader="SGS",
                grade=8.0,
                sold_at=now - timedelta(days=250),
                exact_card=True,
            ),
        ]
        gcc_evidence = watcher.GccMarketEvidence(
            lot=lot,
            sales=gcc_sales,
            estimate=None,
            opportunity=None,
            branch=watcher.GCC_BRANCH_REJECTED,
            strength=watcher.EVIDENCE_WEAK,
        )
        candidate = watcher.ValuationCandidate(gcc=gcc_evidence)
        canonical = mm.CanonicalCard(status="EXACT", card_id="c1", name="Card", set_id="s1", set_name="Set", local_id="1", full_number="1", language_code="fr")

        # Only current PSA 8 comps exist
        poketrace = watcher.ExternalMarketEvidence(
            identity_key=watcher.external_commercial_identity_key(lot),
            status=watcher.EXTERNAL_MATCHED,
            strength=watcher.EVIDENCE_WEAK,
            source="poketrace",
            fetched_at=now,
            comparables=[
                watcher.ComparableSale(price=100.0, grader="PSA", grade=8.0, sold_at=now - timedelta(days=2), exact_card=True),
            ],
        )

        lead = mm._collect_price_discovery_lead(candidate, canonical, raw=None, poketrace=poketrace, now=now)
        self.assertIsNotNone(lead)
        sig = lead.discovery_signal
        # Must fail closed: no invented extrapolation
        self.assertFalse(sig.is_extrapolated)
        self.assertIsNone(sig.temporally_adjusted_central)
        self.assertNotEqual(sig.evidence_level, pd.EVIDENCE_LEVEL_TEMPORALLY_ADJUSTED)



    def test_11_single_current_psa_outlier_does_not_become_robust_reference_value(self):
        """
        Negative test: If current PSA comps have prices [98.0, 100.0, 102.0, 1000.0 (outlier)],
        compute_robust_reference_value must return ~100.0, not 1000.0 or 325.0.
        """
        prices = [98.0, 100.0, 102.0, 1000.0]
        robust_ref = pd.compute_robust_reference_value(prices)
        self.assertAlmostEqual(robust_ref, 100.0, delta=2.0)


    def test_12_psa_benchmark_applies_language_haircuts_and_does_not_take_max(self):
        """PSA benchmark applies language haircuts directly to the benchmark price calculation."""
        anchor_en = pd.AdjacentAnchor(
            anchor_type="PSA_SAME_GRADE",
            source="ebay_sold",
            grader="PSA",
            grade="10",
            language="en",
            price=200.0,
            price_type="SOLD",
            sale_count=1,
            weight=1.0,
        )
        sig = pd.evaluate_price_discovery(
            listing_identity="Mew EN",
            gcc_price=40.0,
            grader="PCA",
            grade="10",
            target_language="fr",
            adjacent_anchors=[anchor_en],
        )
        # English anchor weight is halved (0.50), robust ref becomes ~100.0, not raw 200.0
        self.assertAlmostEqual(sig.credible_high_reference, 100.0, delta=5.0)

    def test_13_cross_language_anchor_alone_fails_closed_manual_review(self):
        """Cross-language anchor alone without same-language / raw support cannot trigger manual review."""
        anchor_en = pd.AdjacentAnchor(
            anchor_type="PSA_SAME_GRADE",
            source="ebay_sold",
            grader="PSA",
            grade="10",
            language="en",
            price=200.0,
            price_type="SOLD",
            sale_count=1,
            weight=1.0,
        )
        sig = pd.evaluate_price_discovery(
            listing_identity="Mew EN",
            gcc_price=40.0,
            grader="PCA",
            grade="10",
            target_language="fr",
            adjacent_anchors=[anchor_en],
        )
        self.assertFalse(sig.manual_review_recommended)

    def test_14_liquidity_based_on_recent_sales_only(self):
        """Target grader with 5 exact sales older than 90 days remains LIQUIDITY_LOW."""
        now = datetime(2026, 8, 12, 12, 0, 0, tzinfo=timezone.utc)
        exact_sales = [
            watcher.ComparableSale(price=50.0, grader="PCA", grade=10.0, sold_at=now - timedelta(days=120), exact_card=True)
            for _ in range(5)
        ]
        sig = pd.evaluate_price_discovery(
            listing_identity="Mew PCA 10",
            gcc_price=40.0,
            grader="PCA",
            grade="10",
            exact_grader_sales=exact_sales,
            target_language="fr",
            now=now,
        )
        self.assertEqual(sig.exact_grader_liquidity, pd.LIQUIDITY_LOW)
        self.assertEqual(sig.liquidity, pd.LIQUIDITY_LOW)

    def test_15_psa_10_anchor_alone_cannot_create_bgs_9_5_opportunity(self):
        """A PSA 10 anchor alone must NOT create a BGS 9.5 opportunity (wide-grade constraint)."""
        anchor_psa10 = pd.AdjacentAnchor(
            anchor_type="PSA_SAME_GRADE",
            source="poketrace",
            grader="PSA",
            grade="10",
            language="fr",
            price=250.0,
            price_type="SOLD",
            sale_count=5,
        )
        sig = pd.evaluate_price_discovery(
            listing_identity="Rayquaza BGS 9.5",
            gcc_price=50.0,
            grader="BGS",
            grade="9.5",
            language="fr",
            adjacent_anchors=[anchor_psa10],
        )
        self.assertFalse(sig.manual_review_recommended)


if __name__ == "__main__":
    unittest.main()
