from __future__ import annotations

import unittest

import watcher
import v4_pricecharting_mandatory_policy as policy


def _lot(*, grade="9", grader="PSA"):
    return watcher.Lot(
        url="https://gradedcardcenter.com/item/test",
        title="Poochyena",
        current_price=30.0,
        source_type="auction",
        grader=grader,
        grade=grade,
        card_set="VSTAR Universe",
        card_number="208/172",
        language="Japanese",
    )


def _guide_evidence(lot, *, central=50.0, strength=watcher.EVIDENCE_WEAK):
    estimate = watcher.MarketEstimate(
        low=central,
        central=central,
        high=central,
        kept_comparables=[],
        rejected_outliers=[],
        recent_90_count=0,
        dated_count=0,
        liquidity="non mesurée",
        dispersion="guide ponctuel",
        confidence="faible",
        adaptive_discount_pct=50.0,
        rationale="base PriceCharting guide",
        source_counts={"pricecharting_guide": 1},
        exact_grade_count=0,
        same_grader_count=0,
        source_consistent=True,
        grade_arbitrage=False,
    )
    return watcher.ExternalMarketEvidence(
        watcher.external_commercial_identity_key(lot),
        watcher.EXTERNAL_MATCHED,
        strength,
        "pricecharting",
        estimate=estimate,
        comparables=[],
        note="PriceCharting guide; not item-level SOLD",
    )


class MandatoryPriceChartingPolicyTests(unittest.TestCase):
    def test_grade9_guide_is_accepted_as_psa9_valuation_guide(self):
        lot = _lot(grade="9")
        upgraded = policy._upgrade_guide_evidence(lot, _guide_evidence(lot))
        self.assertEqual(upgraded.strength, watcher.EVIDENCE_STRONG)
        self.assertEqual(upgraded.estimate.adaptive_discount_pct, watcher.MIN_DISCOUNT)
        self.assertIn("Grade 9 -> PSA 9", upgraded.estimate.rationale)
        self.assertEqual(upgraded.estimate.exact_grade_count, 0)
        self.assertIn("pas un SOLD item-level", upgraded.note)

    def test_grade8_guide_is_accepted_as_psa8_valuation_guide(self):
        lot = _lot(grade="8")
        upgraded = policy._upgrade_guide_evidence(lot, _guide_evidence(lot))
        self.assertEqual(upgraded.strength, watcher.EVIDENCE_STRONG)
        self.assertEqual(upgraded.estimate.adaptive_discount_pct, watcher.MIN_DISCOUNT)
        self.assertIn("Grade 8 -> PSA 8", upgraded.estimate.rationale)

    def test_psa10_guide_uses_normal_discount_not_special_40pct_floor(self):
        lot = _lot(grade="10")
        upgraded = policy._upgrade_guide_evidence(
            lot, _guide_evidence(lot, strength=watcher.EVIDENCE_STRONG)
        )
        self.assertEqual(upgraded.strength, watcher.EVIDENCE_STRONG)
        self.assertEqual(upgraded.estimate.adaptive_discount_pct, watcher.MIN_DISCOUNT)
        self.assertIn("PSA 10", upgraded.estimate.rationale)

    def test_psa85_is_not_silently_mapped_to_grade8(self):
        lot = _lot(grade="8.5")
        original = _guide_evidence(lot)
        upgraded = policy._upgrade_guide_evidence(lot, original)
        self.assertEqual(upgraded.strength, watcher.EVIDENCE_WEAK)
        self.assertEqual(upgraded.estimate.adaptive_discount_pct, 50.0)

    def test_other_grader_is_not_relabelled_as_psa(self):
        lot = _lot(grade="9", grader="CGC")
        original = _guide_evidence(lot)
        upgraded = policy._upgrade_guide_evidence(lot, original)
        self.assertEqual(upgraded.strength, watcher.EVIDENCE_WEAK)
        self.assertNotIn("PSA 9", upgraded.estimate.rationale)


if __name__ == "__main__":
    unittest.main()
