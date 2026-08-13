from __future__ import annotations

import unittest
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as mm
import v4_raw_consensus as raw_consensus
from v4_raw_consensus import RawReasonCode


def make_lot(
    title: str = "Charizard",
    price: float = 50.0,
    grader: str = "PCA",
    grade: float = 8.0,
    language: str = "fr",
    variant: str = "Holo",
    card_number: str = "4/102",
    card_set: str = "Base Set",
) -> watcher.Lot:
    return watcher.Lot(
        url="https://gradedcardcenter.com/item/item-test-1",
        title=f"{title} {grader} {grade}",
        current_price=price,
        source_type="auction",
        grader=grader,
        grade=str(grade),
        card_number=card_number,
        card_set=card_set,
        language=language,
        variant=variant,
    )


class V4RobustRawConsensusAndBackportTests(unittest.TestCase):
    def setUp(self):
        mm._DIAGNOSTICS = mm.MultiMarketDiagnostics()

    def test_1_wrong_language_fails_closed(self):
        """Non-matching third-party language data must be rejected with LANGUAGE_MISMATCH."""
        lot = make_lot(title="Pikachu", language="ja")
        dims = {"language": "japanese"}
        is_compat, reason, msg = raw_consensus.validate_microvariant_compatibility(
            listing_dimensions=dims,
            provider_variant="normal",
            provider_language="de",
            lot_language="ja",
        )
        self.assertFalse(is_compat)
        self.assertEqual(reason, RawReasonCode.LANGUAGE_MISMATCH)

        # Test JustTCG estimator with wrong language
        jt_data = {"price": 50.0, "language": "de", "currency": "EUR", "condition": "NM", "variant": "normal"}
        est = raw_consensus.estimate_justtcg_raw(
            jt_data, variant="normal", lot_language="ja", listing_dimensions=dims
        )
        self.assertIsNotNone(est)
        self.assertEqual(est.confidence, "REJECTED")
        self.assertEqual(est.reason_code, RawReasonCode.LANGUAGE_MISMATCH)


    def test_2_wrong_set_or_number_mismatch(self):
        """Mismatched set/number in TCGdex resolution fails-closed."""
        lot = make_lot(title="Charizard", card_number="4/102", card_set="Base Set")
        mismatched_card = {
            "id": "base-4",
            "name": "Charizard",
            "localId": "4",
            "set": {"id": "base", "name": "Base Set", "cardCount": {"official": "64"}},
        }
        validated = mm._validate_tcgdex_card(
            lot, mismatched_card, language_code="en", unique_name_number=False, reason="test"
        )
        self.assertIsNone(validated)

    def test_3_wrong_holo_reverse_finish_mismatch(self):
        """Holo listing vs normal/reverse candidate without catalog proof fails closed."""
        dims = {"finish": "holo"}
        is_compat, reason, msg = raw_consensus.validate_microvariant_compatibility(
            listing_dimensions=dims,
            provider_variant="normal",
            provider_language="fr",
            lot_language="fr",
            catalog_proven_finish=None,
        )
        self.assertFalse(is_compat)
        self.assertEqual(reason, RawReasonCode.FINISH_MISMATCH)

        # Reverse vs Holo
        is_compat_rev, reason_rev, _ = raw_consensus.validate_microvariant_compatibility(
            listing_dimensions=dims,
            provider_variant="reverse",
            provider_language="fr",
            lot_language="fr",
            catalog_proven_finish=None,
        )
        self.assertFalse(is_compat_rev)
        self.assertEqual(reason_rev, RawReasonCode.FINISH_MISMATCH)

    def test_4_promo_mismatch_symmetric_both_directions(self):
        """HIGH-1: Promo mismatch must reject in BOTH directions fail-closed."""
        # Direction 1: listing promo, provider regular/non-promo
        listing_promo = {"printing": "promo"}
        compat1, reason1, _ = raw_consensus.validate_microvariant_compatibility(
            listing_dimensions=listing_promo,
            provider_variant="normal",
            provider_language="fr",
            lot_language="fr",
        )
        self.assertFalse(compat1)
        self.assertEqual(reason1, RawReasonCode.PROMO_MISMATCH)

        # Direction 2: listing regular/non-promo, provider promo
        listing_regular = {"printing": "regular"}
        compat2, reason2, _ = raw_consensus.validate_microvariant_compatibility(
            listing_dimensions=listing_regular,
            provider_variant="promo",
            provider_language="fr",
            lot_language="fr",
        )
        self.assertFalse(compat2)
        self.assertEqual(reason2, RawReasonCode.PROMO_MISMATCH)

        # Direction 2 with empty listing dimensions vs promo provider candidate
        compat3, reason3, _ = raw_consensus.validate_microvariant_compatibility(
            listing_dimensions={},
            provider_variant="black-star-promo",
            provider_language="fr",
            lot_language="fr",
        )
        self.assertFalse(compat3)
        self.assertEqual(reason3, RawReasonCode.PROMO_MISMATCH)

        # Both promo matches
        compat_both, reason_both, _ = raw_consensus.validate_microvariant_compatibility(
            listing_dimensions={"printing": "promo"},
            provider_variant="promo",
            provider_language="fr",
            lot_language="fr",
        )
        self.assertTrue(compat_both)
        self.assertEqual(reason_both, RawReasonCode.EXACT_COMPATIBLE)

    def test_5_normalized_edition_semantics_adversarial(self):
        """HIGH-2: Edition normalizer handles spaced, hyphenated, compact, camelCase, and multilingual forms."""
        # Adversarial 1st Edition variations
        variations_1st = [
            "1st Edition",
            "1st-edition",
            "1stedition",
            "1stEdition",
            "first edition",
            "firstEdition",
            "1. Edition",
            "1ère Édition",
            "1ere edition",
            "1ere ed",
            "Prima Edizione",
            "1a Edición",
            "1a edicion",
        ]
        for var in variations_1st:
            self.assertEqual(
                raw_consensus.normalize_edition_str(var),
                "first_edition",
                f"Failed to normalize 1st edition variation: {var}",
            )

        # Adversarial Unlimited variations
        variations_unl = [
            "Unlimited",
            "unlimited",
            "illimitée",
            "illimitee",
            "unbegrenzt",
            "illimitata",
            "ilimitada",
        ]
        for var in variations_unl:
            self.assertEqual(
                raw_consensus.normalize_edition_str(var),
                "unlimited",
                f"Failed to normalize unlimited variation: {var}",
            )

        # 1st Edition vs Unlimited / Shadowless fails closed
        compat_1st_unl, reason_1st_unl, _ = raw_consensus.validate_microvariant_compatibility(
            listing_dimensions={"edition": "1st Edition"},
            provider_variant="unlimited",
            provider_language="fr",
            lot_language="fr",
        )
        self.assertFalse(compat_1st_unl)
        self.assertEqual(reason_1st_unl, RawReasonCode.EDITION_MISMATCH)

        compat_unl_1st, reason_unl_1st, _ = raw_consensus.validate_microvariant_compatibility(
            listing_dimensions={"edition": "unlimited"},
            provider_variant="1stEdition",
            provider_language="fr",
            lot_language="fr",
        )
        self.assertFalse(compat_unl_1st)
        self.assertEqual(reason_unl_1st, RawReasonCode.EDITION_MISMATCH)

        compat_shd_unl, reason_shd_unl, _ = raw_consensus.validate_microvariant_compatibility(
            listing_dimensions={"edition": "shadowless"},
            provider_variant="unlimited",
            provider_language="en",
            lot_language="en",
        )
        self.assertFalse(compat_shd_unl)
        self.assertEqual(reason_shd_unl, RawReasonCode.EDITION_MISMATCH)

    def test_6_compound_variant_decomposition(self):
        """MEDIUM-1: Compound provider strings decompose independently without bypassing edition/finish gates."""
        # 1stEditionHolofoil
        d1 = raw_consensus.decompose_commercial_variant("1stEditionHolofoil")
        self.assertEqual(d1["edition"], "first_edition")
        self.assertEqual(d1["finish"], "holo")

        # 1steditionreverseholo
        d2 = raw_consensus.decompose_commercial_variant("1steditionreverseholo")
        self.assertEqual(d2["edition"], "first_edition")
        self.assertEqual(d2["finish"], "reverse")

        # unlimitedholofoil
        d3 = raw_consensus.decompose_commercial_variant("unlimitedholofoil")
        self.assertEqual(d3["edition"], "unlimited")
        self.assertEqual(d3["finish"], "holo")

        # firstEditionNormal
        d4 = raw_consensus.decompose_commercial_variant("firstEditionNormal")
        self.assertEqual(d4["edition"], "first_edition")
        self.assertEqual(d4["finish"], "non_holo")

        # Compound finish mismatch check: Listing is Holo, candidate is 1steditionreverseholo
        compat_fin, reason_fin, _ = raw_consensus.validate_microvariant_compatibility(
            listing_dimensions={"finish": "holo"},
            provider_variant="1steditionreverseholo",
            provider_language="fr",
            lot_language="fr",
        )
        self.assertFalse(compat_fin)
        self.assertEqual(reason_fin, RawReasonCode.FINISH_MISMATCH)

        # Compound edition mismatch check: Listing is 1st Edition, candidate is unlimitedholofoil
        compat_ed, reason_ed, _ = raw_consensus.validate_microvariant_compatibility(
            listing_dimensions={"edition": "1st Edition", "finish": "holo"},
            provider_variant="unlimitedholofoil",
            provider_language="fr",
            lot_language="fr",
        )
        self.assertFalse(compat_ed)
        self.assertEqual(reason_ed, RawReasonCode.EDITION_MISMATCH)

        # Exact compound match
        compat_ok, reason_ok, _ = raw_consensus.validate_microvariant_compatibility(
            listing_dimensions={"edition": "1st Edition", "finish": "holo"},
            provider_variant="1stEditionHolofoil",
            provider_language="fr",
            lot_language="fr",
        )
        self.assertTrue(compat_ok)
        self.assertEqual(reason_ok, RawReasonCode.EXACT_COMPATIBLE)

    def test_7_tcgdex_single_variant_catalog_proof(self):
        """TCGdex proving exactly one variant enables deterministic finish resolution."""
        variants = {"normal": False, "holo": True, "reverse": False}
        proven = raw_consensus.get_catalog_proven_finish(variants)
        self.assertEqual(proven, "holo")

        canonical = mm.CanonicalCard(
            "EXACT",
            card_id="swsh1-1",
            set_id="swsh1",
            set_name="Sword & Shield",
            local_id="1",
            full_number="1/202",
            name="Celebi V",
            language_code="fr",
            variants=variants,
        )
        lot = make_lot(title="Celebi V 1/202 PSA 9", variant="")
        variant, is_det = mm._raw_variant_choice(lot, canonical)
        self.assertTrue(is_det)
        self.assertEqual(variant, "holo")

    def test_8_provider_metadata_alone_cannot_prove_uniqueness(self):
        """When multiple variants exist in catalog, uniqueness is not inferred."""
        multi_variants = {"normal": True, "holo": False, "reverse": True}
        self.assertIsNone(raw_consensus.get_catalog_proven_finish(multi_variants))
        self.assertIsNone(raw_consensus.get_catalog_proven_finish({}))

        canonical = mm.CanonicalCard(
            "EXACT",
            card_id="base-4",
            set_id="base",
            set_name="Base Set",
            local_id="4",
            full_number="4/102",
            name="Charizard",
            language_code="fr",
            variants=multi_variants,
        )
        lot = make_lot(title="Charizard 4/102 PCA 8", variant="")
        variant, is_det = mm._raw_variant_choice(lot, canonical)
        self.assertFalse(is_det)
        self.assertEqual(variant, "")

    def test_9_justtcg_exact_comparable_accepted(self):
        """Near Mint exact French JustTCG comparable is accepted with EXACT_COMPATIBLE."""
        jt_data = {
            "marketPrice": 45.0,
            "lowPrice": 38.0,
            "highPrice": 52.0,
            "language": "fr",
            "condition": "NM",
            "variant": "holo",
            "currency": "EUR",
            "salesCount": 5,
        }
        est = raw_consensus.estimate_justtcg_raw(
            jt_data, variant="holo", lot_language="fr", listing_dimensions={"finish": "holo"}
        )
        self.assertIsNotNone(est)
        self.assertEqual(est.confidence, "STRONG")
        self.assertEqual(est.status, "ACCEPTED")
        self.assertEqual(est.reason_code, RawReasonCode.EXACT_COMPATIBLE)
        self.assertEqual(est.central, 45.0)

    def test_10_justtcg_mismatch_rejected(self):
        """Mismatched variant in JustTCG is rejected with reason code."""
        jt_data = {"marketPrice": 45.0, "language": "fr", "currency": "EUR", "condition": "NM", "variant": "normal"}
        est = raw_consensus.estimate_justtcg_raw(
            jt_data, variant="normal", lot_language="fr", listing_dimensions={"finish": "holo"}
        )
        self.assertIsNotNone(est)
        self.assertEqual(est.confidence, "REJECTED")
        self.assertEqual(est.reason_code, RawReasonCode.FINISH_MISMATCH)

    def test_11_single_justtcg_cannot_trigger_opportunity(self):
        """MEDIUM-3: A single JustTCG source is diagnostic (WEAK) and cannot trigger opportunity."""
        target_lot = make_lot(title="Pikachu", price=20.0, grader="PCA", grade=8.0, language="fr", variant="Holo")
        canonical = mm.CanonicalCard(
            "EXACT",
            card_id="swsh-25",
            set_id="swsh",
            set_name="Base",
            local_id="25",
            full_number="25/202",
            name="Pikachu",
            language_code="fr",
            pricing={
                "cardmarket": {
                    "trend-holo": 100.0,
                    "avg-holo": 100.0,
                    "avg7-holo": 95.0,
                    "avg30-holo": 98.0,
                    "low-holo": 85.0,
                }
            },
            variants={"normal": False, "holo": True, "reverse": False},
        )

        signal = mm.raw_market_signal(target_lot, canonical)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.confidence, "WEAK")
        self.assertEqual(len(signal.sources), 1)

        # Gate check: Single source cannot trigger opportunity notification
        should_review, _ = mm._should_manual_review(target_lot, signal)
        self.assertFalse(should_review)

        # Also verify single JustTCG adapter estimate is arbitrated as WEAK
        justtcg_est = raw_consensus.estimate_justtcg_raw(
            {"currency": "EUR", "language": "fr", "condition": "NM", "variant": "holo", "marketPrice": 100.0},
            variant="holo",
            lot_language="fr",
        )
        consensus_res = raw_consensus.arbitrate_raw_consensus([justtcg_est], lot_language="fr")
        self.assertEqual(consensus_res.confidence, "WEAK")


    def test_12_ambiguous_path_excludes_incompatible_tiers(self):
        """MEDIUM-2: _all_raw_centers filters out incompatible provider tiers."""
        target_lot = make_lot(
            title="Charizard 1st Edition",
            price=200.0,
            grader="PCA",
            grade=8.0,
            language="en",
            variant="1st Edition",
        )
        canonical = mm.CanonicalCard(
            "EXACT",
            card_id="base1-4",
            set_id="base1",
            set_name="Base Set",
            local_id="4",
            full_number="4/102",
            name="Charizard",
            language_code="en",
            pricing={
                "tcgplayer": {
                    "unit": "USD",
                    "unlimitedHolofoil": {"marketPrice": 300.0},
                    "1stEditionHolofoil": {"marketPrice": 3000.0},
                }
            },
            variants={"normal": False, "holo": True, "reverse": False},
        )

        with patch.object(raw_consensus, "_usd_per_eur", return_value=1.08):
            centers = mm._all_raw_centers(canonical, target_lot)

        # Incompatible unlimited tier must be excluded when listing is 1st Edition
        tier_names = [var for _, _, var in centers]
        self.assertIn("1stEditionHolofoil", tier_names)
        self.assertNotIn("unlimitedHolofoil", tier_names)

    def test_13_clean_two_plus_provider_consensus_triggers(self):
        """When 2+ compatible independent providers agree on a deep discount, opportunity triggers."""
        target_lot = make_lot(title="Gengar", price=40.0, grader="PCA", grade=8.0, language="fr", variant="Holo")
        canonical = mm.CanonicalCard(
            "EXACT",
            card_id="xy-94",
            set_id="xy",
            set_name="Phantom Forces",
            local_id="94",
            full_number="94/119",
            name="Gengar EX",
            language_code="fr",
            pricing={
                "cardmarket": {
                    "trend-holo": 105.0,
                    "avg7-holo": 100.0,
                    "avg30-holo": 98.0,
                    "avg-holo": 102.0,
                    "low-holo": 88.0,
                },
                "tcgplayer": {
                    "unit": "USD",
                    "holofoil": {"marketPrice": 108.0, "lowPrice": 95.0},
                },
                "justtcg": {
                    "currency": "EUR",
                    "language": "fr",
                    "marketPrice": 100.0,
                    "lowPrice": 90.0,
                    "highPrice": 115.0,
                },
            },
            variants={"normal": False, "holo": True, "reverse": False},
        )

        with patch.object(raw_consensus, "_usd_per_eur", return_value=1.08):
            signal = mm.raw_market_signal(target_lot, canonical)

        self.assertIsNotNone(signal)
        self.assertEqual(signal.confidence, "STRONG")
        self.assertGreaterEqual(signal.central, 95.0)

        should_review, gap = mm._should_manual_review(target_lot, signal)
        self.assertTrue(should_review)
        self.assertGreaterEqual(gap, 0.45)

    def test_14_cardmarket_mew_xy110_outlier_rejection(self):
        """Mew XY110 PCA 8 @ 75€ must reject Cardmarket ~334€ outlier and send 0 notifications."""
        target_lot = make_lot(
            title="Mew", price=75.0, grader="PCA", grade=8.0, language="fr", variant="Holo", card_number="XY110"
        )
        canonical = mm.CanonicalCard(
            "EXACT",
            card_id="xy-XY110",
            set_id="xy",
            set_name="Promo XY",
            local_id="XY110",
            full_number="XY110",
            name="Mew",
            language_code="fr",
            pricing={
                "cardmarket": {
                    "trend-holo": 313.34,
                    "avg30-holo": 349.03,
                    "avg7-holo": 114.35,
                    "avg-holo": 355.08,
                    "low-holo": 20.00,
                },
                "tcgplayer": {
                    "unit": "USD",
                    "holofoil": {"marketPrice": 28.00, "lowPrice": 22.00},
                },
                "justtcg": {
                    "currency": "EUR",
                    "language": "fr",
                    "condition": "NM",
                    "variant": "holo",
                    "marketPrice": 32.00,
                    "lowPrice": 25.00,
                    "highPrice": 38.00,
                },
            },

            variants={"normal": False, "holo": True, "reverse": False},
        )

        with patch.object(raw_consensus, "_usd_per_eur", return_value=1.08):
            signal = mm.raw_market_signal(target_lot, canonical)

        self.assertIsNotNone(signal)
        # Cardmarket outlier was identified and rejected
        self.assertTrue(
            any("Cardmarket" in r for r in signal.providers_rejected)
            or signal.confidence in {"STRONG", "MODERATE"}
        )
        self.assertLess(signal.central, 45.0)

        # Gate check: 75€ lot against ~25-30€ RAW market is NOT an opportunity
        should_review, gap = mm._should_manual_review(target_lot, signal)
        self.assertFalse(should_review)
        self.assertLessEqual(gap, 0.0)



    def test_15_cardmarket_holo_without_holo_keys_rejects_unless_catalog_proven(self):
        """Cardmarket data with generic keys cannot masquerade as holo unless catalog proves single holo finish."""
        cm_data = {"trend": 100.0, "avg": 95.0, "avg7": 90.0, "avg30": 92.0}

        # When catalog does not prove single finish: must reject
        est_unproven = raw_consensus.estimate_cardmarket_raw(
            cm_data, variant="holo", lot_language="fr", catalog_proven_finish=None
        )
        self.assertIsNotNone(est_unproven)
        self.assertEqual(est_unproven.confidence, "REJECTED")
        self.assertEqual(est_unproven.reason_code, RawReasonCode.FINISH_MISMATCH)

        # When catalog proves card only exists in holo: accept generic
        est_proven = raw_consensus.estimate_cardmarket_raw(
            cm_data, variant="holo", lot_language="fr", catalog_proven_finish="holo"
        )
        self.assertIsNotNone(est_proven)
        self.assertEqual(est_proven.status, "ACCEPTED")
        self.assertEqual(est_proven.central, 93.5)

    def test_16_justtcg_missing_dimensions_fails_closed(self):
        """JustTCG responses missing explicit language or condition fail closed."""
        # Missing language
        jt_no_lang = {"marketPrice": 50.0, "condition": "NM"}
        est_no_lang = raw_consensus.estimate_justtcg_raw(jt_no_lang, variant="normal", lot_language="fr")
        self.assertIsNotNone(est_no_lang)
        self.assertEqual(est_no_lang.confidence, "REJECTED")
        self.assertEqual(est_no_lang.reason_code, RawReasonCode.LANGUAGE_MISMATCH)

        # Poor condition
        jt_poor = {"marketPrice": 20.0, "language": "fr", "condition": "POOR"}
        est_poor = raw_consensus.estimate_justtcg_raw(jt_poor, variant="normal", lot_language="fr")
        self.assertIsNotNone(est_poor)
        self.assertEqual(est_poor.confidence, "REJECTED")
        self.assertEqual(est_poor.reason_code, RawReasonCode.INSUFFICIENT_IDENTITY)

    def test_17_pricecharting_and_ebay_accept_catalog_proven_finish_kwarg(self):
        """PriceCharting and eBay estimators must accept catalog_proven_finish kwarg without TypeError."""
        pc_data = {"loose": 45.0, "currency": "USD"}
        with patch.object(raw_consensus, "_usd_per_eur", return_value=1.1):
            est_pc = raw_consensus.estimate_pricecharting_raw(
                pc_data, lot_language="en", catalog_proven_finish="holo"
            )
            self.assertIsNotNone(est_pc)
            self.assertEqual(est_pc.status, "ACCEPTED")

        ebay_data = {"sales": [35.0, 38.0, 40.0], "currency": "EUR", "language": "fr"}
        est_ebay = raw_consensus.estimate_ebay_raw(
            ebay_data, lot_language="fr", catalog_proven_finish="holo"
        )
        self.assertIsNotNone(est_ebay)
        self.assertEqual(est_ebay.status, "ACCEPTED")

    def test_18_justtcg_missing_condition_or_variant_fails_closed(self):
        """JustTCG missing condition or unproven variant must fail closed."""
        # Missing condition key completely
        jt_no_cond = {"marketPrice": 50.0, "language": "fr", "variant": "normal"}
        est_no_cond = raw_consensus.estimate_justtcg_raw(jt_no_cond, variant="normal", lot_language="fr")
        self.assertIsNotNone(est_no_cond)
        self.assertEqual(est_no_cond.confidence, "REJECTED")
        self.assertEqual(est_no_cond.reason_code, RawReasonCode.INSUFFICIENT_IDENTITY)

        # Missing variant key when catalog does not prove unique finish
        jt_no_var = {"marketPrice": 50.0, "language": "fr", "condition": "NM"}
        est_no_var = raw_consensus.estimate_justtcg_raw(jt_no_var, variant="normal", lot_language="fr", catalog_proven_finish=None)
        self.assertIsNotNone(est_no_var)
        self.assertEqual(est_no_var.confidence, "REJECTED")
        self.assertEqual(est_no_var.reason_code, RawReasonCode.INSUFFICIENT_IDENTITY)

    def test_19_ebay_and_pricecharting_missing_dimensions_fail_closed(self):
        """eBay missing language and PriceCharting unproven finish must fail closed."""
        # eBay missing language key
        ebay_no_lang = {"sales": [40.0, 42.0], "currency": "EUR"}
        est_eb_no_lang = raw_consensus.estimate_ebay_raw(ebay_no_lang, lot_language="fr")
        self.assertIsNotNone(est_eb_no_lang)
        self.assertEqual(est_eb_no_lang.confidence, "REJECTED")
        self.assertEqual(est_eb_no_lang.reason_code, RawReasonCode.LANGUAGE_MISMATCH)

        # PriceCharting required holo finish unproven
        pc_data = {"loose": 50.0, "currency": "USD"}
        est_pc_unproven = raw_consensus.estimate_pricecharting_raw(
            pc_data, lot_language="en", listing_dimensions={"finish": "holo"}, catalog_proven_finish=None
        )
        self.assertIsNotNone(est_pc_unproven)
        self.assertEqual(est_pc_unproven.confidence, "REJECTED")
        self.assertEqual(est_pc_unproven.reason_code, RawReasonCode.FINISH_MISMATCH)

    def test_20_ambiguous_envelope_through_all_raw_centers(self):
        """Ambiguous variant envelope correctly queries Cardmarket and TCGplayer through production _all_raw_centers."""
        import v4_canonical_multimarket as mm
        canonical = mm.CanonicalCard(
            "EXACT",
            card_id="base1-4",
            set_id="base1",
            set_name="Base Set",
            local_id="4",
            full_number="4/102",
            name="Charizard",
            language_code="en",
            pricing={
                "cardmarket": {"trend": 100.0, "avg": 105.0},
                "tcgplayer": {"normal": {"marketPrice": 110.0}, "unit": "USD"},
            },
            variants={"normal": True, "holo": True},
            unique_name_number=True,
        )
        target_lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/1",
            title="Charizard 4/102",
            current_price=50.0,
            source_type="auction",
            language="en",
        )
        with patch.object(mm, "_usd_per_eur", return_value=1.08), patch.object(raw_consensus, "_usd_per_eur", return_value=1.08):
            centers = mm._all_raw_centers(canonical, target_lot)
            self.assertTrue(any(src == "Cardmarket" for src, _, _ in centers))
            self.assertTrue(any(src == "TCGplayer" for src, _, _ in centers))

    def test_21_adversarial_missing_dimensions_fail_closed(self):
        """Adversarial validation: missing set, number, edition, language, condition, finish fail closed."""
        # 1. Missing / mismatch set
        pc_wrong_set = {"loose": 50.0, "set": "Neo Genesis", "currency": "USD"}
        est_set = raw_consensus.estimate_pricecharting_raw(
            pc_wrong_set, lot_language="en", listing_dimensions={"set": "Base Set"}
        )
        self.assertIsNotNone(est_set)
        self.assertEqual(est_set.confidence, "REJECTED")
        self.assertEqual(est_set.reason_code, RawReasonCode.INSUFFICIENT_IDENTITY)

        # 2. Missing / mismatch collector number
        eb_wrong_num = {"sales": [50.0, 55.0], "language": "en", "number": "15/102"}
        est_num = raw_consensus.estimate_ebay_raw(
            eb_wrong_num, lot_language="en", listing_dimensions={"number": "4/102"}
        )
        self.assertIsNotNone(est_num)
        self.assertEqual(est_num.confidence, "REJECTED")
        self.assertEqual(est_num.reason_code, RawReasonCode.INSUFFICIENT_IDENTITY)

        # 3. Required 1st Edition unproven
        is_compat, reason, _ = raw_consensus.validate_microvariant_compatibility(
            {"edition": "1st edition"}, "normal", "en", "en"
        )
        self.assertFalse(is_compat)
        self.assertEqual(reason, RawReasonCode.EDITION_MISMATCH)

        # 4. Japanese language on Cardmarket (fails closed)
        cm_ja = {"trend": 100.0, "avg": 100.0}
        est_ja = raw_consensus.estimate_cardmarket_raw(cm_ja, variant="normal", lot_language="ja")
        self.assertIsNotNone(est_ja)
        self.assertEqual(est_ja.confidence, "REJECTED")
        self.assertEqual(est_ja.reason_code, RawReasonCode.LANGUAGE_MISMATCH)

        # 5. TCGplayer non-NM condition
        tp_lp = {"normal": {"marketPrice": 50.0, "condition": "LP"}, "unit": "USD"}
        est_tp_lp = raw_consensus.estimate_tcgplayer_raw(tp_lp, variant="normal", lot_language="en")
        self.assertIsNotNone(est_tp_lp)
        self.assertEqual(est_tp_lp.confidence, "REJECTED")
        self.assertEqual(est_tp_lp.reason_code, RawReasonCode.INSUFFICIENT_IDENTITY)

        # 6. Cardmarket generic price without holo keys when listing requires holo
        cm_no_holo = {"trend": 20.0, "avg": 22.0}
        est_cm_no_holo = raw_consensus.estimate_cardmarket_raw(
            cm_no_holo, variant="holo", lot_language="fr", catalog_proven_finish=None
        )
        self.assertIsNotNone(est_cm_no_holo)
        self.assertEqual(est_cm_no_holo.confidence, "REJECTED")
        self.assertEqual(est_cm_no_holo.reason_code, RawReasonCode.FINISH_MISMATCH)


if __name__ == "__main__":
    unittest.main()

