from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import v4_external_coverage_drain as drain
import v4_price_discovery as price_discovery
import watcher


NOW = datetime(2026, 8, 16, 20, 0, tzinfo=timezone.utc)


def make_lot(
    item_id: str,
    *,
    source_type: str = "fixed",
    price: float = 80.0,
    language: str = "French",
) -> watcher.Lot:
    return watcher.Lot(
        url=f"https://gradedcardcenter.com/item/{item_id}",
        title="Charizard",
        current_price=price,
        source_type=source_type,
        grader="PSA",
        grade="10",
        card_set="Base Set",
        card_number="4/102",
        language=language,
        body=(
            "Catégorie: Pokémon\n"
            "Référence: #4/102\n"
            "Série: Base Set\n"
            f"Langue: {language}\n"
            "Société de gradation: PSA\n"
            "Note: 10\n"
        ),
    )


def make_queue_state(lot: watcher.Lot) -> tuple[dict, dict]:
    item_id = watcher.fixed_listing_id(lot)
    record = {
        "item_id": item_id,
        "first_seen_at": (NOW - timedelta(days=2)).isoformat(),
        "last_seen_at": NOW.isoformat(),
        "last_evaluated_at": (NOW - timedelta(hours=1)).isoformat(),
        "last_price": lot.current_price,
        "metadata_fingerprint": watcher.fixed_metadata_fingerprint(lot),
        "evaluated_fingerprint": watcher.fixed_metadata_fingerprint(lot),
        "evaluation_version": watcher.ECONOMIC_EVALUATION_VERSION,
        "last_evaluation_status": watcher.REJECTION_EXTERNAL_PENDING,
        "retry_count": 0,
        "retry_after": None,
        "active": True,
    }
    state = {
        watcher.FIXED_QUEUE_STATE_KEY: {
            "schema_version": watcher.FIXED_QUEUE_SCHEMA_VERSION,
            "items": {item_id: record},
        }
    }
    return state, record


class ExternalCoverageDrainTests(unittest.TestCase):
    def test_eight_card_budget_reserves_four_for_fixed(self):
        auction = watcher.ValuationCandidate(
            gcc=watcher.GccMarketEvidence(
                lot=make_lot("auction", source_type="auction"),
                sales=[],
                estimate=None,
                opportunity=None,
                branch=watcher.GCC_BRANCH_UNAVAILABLE,
                strength=watcher.EVIDENCE_UNAVAILABLE,
            )
        )
        fixed = watcher.ValuationCandidate(
            gcc=watcher.GccMarketEvidence(
                lot=make_lot("fixed", source_type="fixed"),
                sales=[],
                estimate=None,
                opportunity=None,
                branch=watcher.GCC_BRANCH_UNAVAILABLE,
                strength=watcher.EVIDENCE_UNAVAILABLE,
            )
        )

        self.assertEqual(
            drain._effective_ebay_cap_for_candidate(
                auction, total_cap=8, fixed_reserve=4
            ),
            4,
        )
        self.assertEqual(
            drain._effective_ebay_cap_for_candidate(
                fixed, total_cap=8, fixed_reserve=4
            ),
            8,
        )

    def test_budget_pending_never_gets_exponential_backoff(self):
        lot = make_lot("budget-pending")
        state, record = make_queue_state(lot)
        previous = drain._ORIGINAL_RECORD_FIXED_EXTERNAL_STATUS
        drain._ORIGINAL_RECORD_FIXED_EXTERNAL_STATUS = watcher._record_fixed_external_status
        try:
            with patch.dict(
                os.environ,
                {"V4_EXTERNAL_PENDING_BUDGET_COOLDOWN_MINUTES": "5"},
                clear=False,
            ):
                drain._record_fixed_external_status_with_budget_semantics(
                    state,
                    lot,
                    watcher.REJECTION_EXTERNAL_PENDING,
                    run_now=NOW,
                )
                self.assertEqual(record["retry_count"], 0)
                self.assertEqual(
                    record["retry_after"],
                    (NOW + timedelta(minutes=5)).isoformat(),
                )

                later = NOW + timedelta(minutes=10)
                drain._record_fixed_external_status_with_budget_semantics(
                    state,
                    lot,
                    watcher.REJECTION_EXTERNAL_PENDING,
                    run_now=later,
                )
                self.assertEqual(record["retry_count"], 0)
                self.assertEqual(
                    record["retry_after"],
                    (later + timedelta(minutes=5)).isoformat(),
                )
        finally:
            drain._ORIGINAL_RECORD_FIXED_EXTERNAL_STATUS = previous

    def test_real_provider_retry_keeps_exponential_backoff(self):
        lot = make_lot("provider-retry")
        state, record = make_queue_state(lot)
        previous = drain._ORIGINAL_RECORD_FIXED_EXTERNAL_STATUS
        drain._ORIGINAL_RECORD_FIXED_EXTERNAL_STATUS = watcher._record_fixed_external_status
        try:
            drain._record_fixed_external_status_with_budget_semantics(
                state,
                lot,
                watcher.REJECTION_EXTERNAL_RETRY,
                run_now=NOW,
            )
            self.assertEqual(record["retry_count"], 1)
            self.assertEqual(
                record["retry_after"],
                (NOW + timedelta(minutes=15)).isoformat(),
            )
            later = NOW + timedelta(minutes=15)
            drain._record_fixed_external_status_with_budget_semantics(
                state,
                lot,
                watcher.REJECTION_EXTERNAL_RETRY,
                run_now=later,
            )
            self.assertEqual(record["retry_count"], 2)
            self.assertEqual(
                record["retry_after"],
                (later + timedelta(minutes=30)).isoformat(),
            )
        finally:
            drain._ORIGINAL_RECORD_FIXED_EXTERNAL_STATUS = previous

    def test_legacy_budget_pending_backoff_is_migrated_but_provider_retry_is_not(self):
        lot = make_lot("legacy-budget")
        state, budget_record = make_queue_state(lot)
        budget_record["retry_count"] = 6
        budget_record["retry_after"] = (NOW + timedelta(hours=6)).isoformat()

        provider_lot = make_lot("provider-error")
        provider_id = watcher.fixed_listing_id(provider_lot)
        provider_record = dict(budget_record)
        provider_record["item_id"] = provider_id
        provider_record["last_evaluation_status"] = watcher.REJECTION_EXTERNAL_RETRY
        state[watcher.FIXED_QUEUE_STATE_KEY]["items"][provider_id] = provider_record

        migrated = drain._normalize_legacy_budget_pending_backoff(state, NOW)
        self.assertEqual(migrated, 1)
        self.assertEqual(budget_record["retry_count"], 0)
        self.assertEqual(budget_record["retry_after"], NOW.isoformat())
        self.assertEqual(provider_record["retry_count"], 6)
        self.assertEqual(
            provider_record["retry_after"],
            (NOW + timedelta(hours=6)).isoformat(),
        )


class FrenchGccOpportunityPolicyTests(unittest.TestCase):
    def test_french_gcc_card_with_sufficient_exact_sold_history_is_eligible(self):
        lot = make_lot("fr-opportunity", price=80.0, language="French")
        sales = [
            watcher.ComparableSale(
                price=price,
                source="gcc",
                grader="PSA",
                grade=10.0,
                sold_at=NOW - timedelta(days=days),
                context="Charizard Base Set 4/102 French PSA 10",
                exact_card=True,
                match_score=100,
            )
            for price, days in ((145.0, 7), (150.0, 18), (155.0, 35), (148.0, 62))
        ]

        evidence = watcher.build_gcc_market_evidence(
            lot,
            sales,
            now=NOW,
            require_external_identity=True,
        )
        self.assertEqual(evidence.branch, watcher.GCC_BRANCH_SUPPORTED)
        self.assertIsNotNone(evidence.opportunity)
        self.assertGreaterEqual(evidence.opportunity.discount_pct, 30.0)

    def test_en_and_ja_anchors_are_secondary_for_a_french_listing(self):
        anchors = [
            price_discovery.AdjacentAnchor(
                anchor_type="EXACT_GCC_SOLD",
                source="gcc",
                grader="PSA",
                grade="10",
                language="fr",
                price=150.0,
                price_type="SOLD",
                sale_count=3,
            ),
            price_discovery.AdjacentAnchor(
                anchor_type="PSA_SAME_GRADE",
                source="ebay",
                grader="PSA",
                grade="10",
                language="en",
                price=180.0,
                price_type="SOLD",
                sale_count=3,
            ),
            price_discovery.AdjacentAnchor(
                anchor_type="PSA_SAME_GRADE",
                source="poketrace",
                grader="PSA",
                grade="10",
                language="ja",
                price=200.0,
                price_type="SOLD",
                sale_count=3,
            ),
        ]

        signal = price_discovery.evaluate_price_discovery(
            listing_identity="Charizard Base Set 4/102 FR PSA10",
            gcc_price=80.0,
            grader="PSA",
            grade="10",
            language="fr",
            exact_grader_sales=[145.0, 150.0, 155.0],
            adjacent_anchors=anchors,
        )

        by_lang = {anchor.language: anchor for anchor in signal.credible_adjacent_anchors}
        self.assertEqual(by_lang["fr"].weight, 1.0)
        self.assertEqual(by_lang["en"].weight, 0.5)
        self.assertEqual(by_lang["ja"].weight, 0.5)
        self.assertIn(
            "LANGUAGE_DIFFERENCE_EN_VS_FR",
            by_lang["en"].uncertainty_reasons,
        )
        self.assertIn(
            "LANGUAGE_DIFFERENCE_JA_VS_FR",
            by_lang["ja"].uncertainty_reasons,
        )


if __name__ == "__main__":
    unittest.main()
