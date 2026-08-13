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
        jt_data = {"price": 50.0, "language": "de", "currency": "EUR"}
        est = raw_consensus.estimate_justtcg_raw(
            jt_data, variant="normal", lot_language="ja", listing_dimensions=dims
        )
        self.assertIsNotNone(est)
        self.assertEqual(est.confidence, "REJECTED")
        self.assertEqual(est.reason_code, RawReasonCode.LANGUAGE_MISMATCH)

    def test_2_wrong_set_or_number_mismatch(self):
        """Mismatched set/number in TCGdex resolution fails-closed."""
        lot = make_lot(title="Charizard", card_number="4/102", card_set="Base Set")
        # Card detail with wrong set denominator
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

    def test_4_promo_non_promo_mismatch(self):
        """Promo listing vs regular non-promo candidate fails closed with PROMO_MISMATCH."""
        dims = {"printing": "promo"}
        is_compat, reason, msg = raw_consensus.validate_microvariant_compatibility(
            listing_dimensions=dims,
            provider_variant="normal",
            provider_language="fr",
            lot_language="fr",
        )
        self.assertFalse(is_compat)
        self.assertEqual(reason, RawReasonCode.PROMO_MISMATCH)

    def test_5_first_edition_unlimited_mismatch(self):
        """1st Edition listing vs Unlimited provider candidate fails closed with EDITION_MISMATCH."""
        dims = {"edition": "first_edition"}
        is_compat, reason, msg = raw_consensus.validate_microvariant_compatibility(
            listing_dimensions=dims,
            provider_variant="unlimited-holofoil",
            provider_language="fr",
            lot_language="fr",
        )
        self.assertFalse(is_compat)
        self.assertEqual(reason, RawReasonCode.EDITION_MISMATCH)

    def test_6_multilingual_explicit_title_evidence(self):
        """Multilingual title evidence (German, French, Italian, Spanish) is deterministically parsed."""
        # German 1. Edition + Nicht-Holo
        de_text = "Glurak 4/102 1. Edition Nicht-Holo Deutsch PSA 8"
        de_dims = raw_consensus.parse_multilingual_commercial_dimensions(de_text)
        self.assertEqual(de_dims.get("edition"), "first_edition")
        self.assertEqual(de_dims.get("finish"), "non_holo")
        self.assertEqual(de_dims.get("language"), "german")

        # Italian Prima Edizione + Olografica
        it_text = "Charizard 4/102 Prima Edizione Olografica Italiano PCA 9"
        it_dims = raw_consensus.parse_multilingual_commercial_dimensions(it_text)
        self.assertEqual(it_dims.get("edition"), "first_edition")
        self.assertEqual(it_dims.get("finish"), "holo")
        self.assertEqual(it_dims.get("language"), "italian")

        # French 1ère Édition + Sans Ombre
        fr_text = "Dracaufeu 4/102 1ère Édition Sans Ombre Francais"
        fr_dims = raw_consensus.parse_multilingual_commercial_dimensions(fr_text)
        self.assertEqual(fr_dims.get("edition"), "first_edition")
        self.assertEqual(fr_dims.get("shadow"), "shadowless")
        self.assertEqual(fr_dims.get("language"), "french")

        # Reverse Poke Ball & Master Ball
        ball_text = "Pikachu 025/165 Reverse Poke Ball Holo"
        ball_dims = raw_consensus.parse_multilingual_commercial_dimensions(ball_text)
        self.assertEqual(ball_dims.get("special_finish"), "poke_ball")

        # Contradiction fails closed with __conflict__
        conflict_text = "Charizard 1st Edition Unlimited Holo"
        conflict_dims = raw_consensus.parse_multilingual_commercial_dimensions(conflict_text)
        self.assertEqual(conflict_dims.get("edition"), "__conflict__")

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
        # Without explicit finish in lot or catalog uniqueness, variant choice is ambiguous
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
        jt_data = {"marketPrice": 45.0, "language": "fr", "currency": "EUR"}
        est = raw_consensus.estimate_justtcg_raw(
            jt_data, variant="normal", lot_language="fr", listing_dimensions={"finish": "holo"}
        )
        self.assertIsNotNone(est)
        self.assertEqual(est.confidence, "REJECTED")
        self.assertEqual(est.reason_code, RawReasonCode.FINISH_MISMATCH)

    def test_11_cardmarket_mew_xy110_outlier_rejection(self):
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
        # Consensus central should be around ~25-32€, NOT ~334€
        self.assertLess(signal.central, 45.0)
        self.assertLess(signal.low, 30.0)

        # Gate check: 75€ lot against ~25-30€ RAW market is NOT an opportunity
        should_review, gap = mm._should_manual_review(target_lot, signal)
        self.assertFalse(should_review)
        self.assertLess(gap, 0.0)

    def test_12_clean_multi_provider_raw_opportunity_triggers(self):
        """When Cardmarket, JustTCG, and TCGplayer agree on a truly cheap card, manual review triggers."""
        # Card is genuinely worth ~100€ RAW, offered at 40€ on GCC (60% discount)
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
        self.assertGreaterEqual(signal.low, 80.0)

        should_review, gap = mm._should_manual_review(target_lot, signal)
        self.assertTrue(should_review)
        self.assertGreaterEqual(gap, 0.45)

    def test_13_unavailable_optional_providers_degrade_gracefully(self):
        """Missing or disabled optional providers degrade gracefully without breaking evaluation."""
        target_lot = make_lot(title="Dragonite", price=30.0, grader="PCA", grade=8.0, language="fr", variant="Holo")
        canonical = mm.CanonicalCard(
            "EXACT",
            card_id="xy-52",
            set_id="xy",
            set_name="Roaring Skies",
            local_id="52",
            full_number="52/108",
            name="Dragonite",
            language_code="fr",
            pricing={
                "cardmarket": {
                    "trend-holo": 60.0,
                    "avg7-holo": 58.0,
                    "avg30-holo": 55.0,
                    "avg-holo": 59.0,
                    "low-holo": 48.0,
                }
                # No tcgplayer, no justtcg, no pricecharting
            },
            variants={"normal": False, "holo": True, "reverse": False},
        )

        signal = mm.raw_market_signal(target_lot, canonical)
        self.assertIsNotNone(signal)
        self.assertIn("Cardmarket", signal.sources)
        self.assertEqual(len(signal.sources), 1)
        self.assertEqual(signal.confidence, "MODERATE")
        self.assertGreater(signal.central, 50.0)


if __name__ == "__main__":
    unittest.main()
