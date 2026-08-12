from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as mm


NOW = datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc)


def lot(
    *,
    name="Charizard",
    reference="4/102",
    language="English",
    grader="PSA",
    grade="8",
    price=40.0,
    series="Base Set",
):
    return watcher.Lot(
        url="https://gradedcardcenter.com/item/test-card",
        title=name,
        current_price=price,
        source_type="fixed",
        grader=grader,
        grade=grade,
        card_number=reference,
        card_set=series,
        language=language,
        body=(
            "Catégorie: Pokémon\n"
            f"Référence: #{reference}\n"
            f"Série: {series}\n"
            f"Langue: {language}\n"
            "Article Gradation Détails\n"
            f"Société de gradation: {grader}\n"
            f"Note: {grade}\n"
        ),
    )


def tcgdex_card(
    *,
    card_id="base1-4",
    name="Charizard",
    local_id="4",
    set_id="base1",
    set_name="Base Set",
    official=102,
    total=102,
    variants=None,
    pricing=None,
):
    return {
        "id": card_id,
        "name": name,
        "localId": local_id,
        "set": {
            "id": set_id,
            "name": set_name,
            "cardCount": {"official": official, "total": total},
        },
        "variants": variants
        or {"normal": False, "holo": True, "reverse": False, "firstEdition": False},
        "pricing": pricing or {},
    }


def market_estimate(low=90, central=100, high=110):
    return watcher.MarketEstimate(
        low=low,
        central=central,
        high=high,
        kept_comparables=[],
        rejected_outliers=[],
        recent_90_count=0,
        dated_count=0,
        liquidity="moyenne",
        dispersion="faible",
        confidence="moyenne",
        adaptive_discount_pct=30,
        rationale="external aggregate",
        source_counts={"poketrace": 5},
        exact_grade_count=5,
        same_grader_count=5,
        source_consistent=True,
    )


class PsaProductionScopeTests(unittest.TestCase):
    def test_psa_scope_is_8_8_5_9_and_10_only(self):
        for grade in ("8", "8.5", "9", "10"):
            self.assertTrue(mm.psa_grade_in_production_scope(lot(grade=grade)))
        for grade in ("1", "6", "7", "7.5", "9.5"):
            self.assertFalse(mm.psa_grade_in_production_scope(lot(grade=grade)))

    def test_non_psa_grade_is_unchanged(self):
        self.assertTrue(
            mm.psa_grade_in_production_scope(
                lot(grader="BGS", grade="7")
            )
        )

    def test_scope_filter_accounts_psa_below_8(self):
        mm._DIAGNOSTICS = mm.MultiMarketDiagnostics()
        target = lot(grade="7")
        with patch.object(mm, "_ORIGINAL_IS_VALID_POKEMON_CARD", return_value=True):
            self.assertFalse(mm.scoped_is_valid_pokemon_card(target))
        self.assertEqual(mm._DIAGNOSTICS.psa_below_8_excluded, 1)


class TCGdexCanonicalIdentityTests(unittest.TestCase):
    def setUp(self):
        mm._DIAGNOSTICS = mm.MultiMarketDiagnostics()

    def test_exact_name_and_full_number_resolve_unique_card(self):
        target = lot()
        detail = tcgdex_card()
        responses = [
            (200, [{"id": "base1-4", "name": "Charizard", "localId": "4"}], {}),
            (200, detail, {}),
        ]
        with patch.object(mm, "_json_get", side_effect=responses):
            result = mm.resolve_tcgdex_card(target)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "base1-4")
        self.assertEqual(result.set_id, "base1")
        self.assertTrue(result.unique_name_number)

    def test_same_name_and_number_multiple_sets_is_ambiguous_without_exact_set(self):
        target = lot(series="Unknown GCC label")
        a = tcgdex_card(card_id="a-4", set_id="a", set_name="Set A")
        b = tcgdex_card(card_id="b-4", set_id="b", set_name="Set B")
        responses = [
            (
                200,
                [
                    {"id": "a-4", "name": "Charizard", "localId": "4"},
                    {"id": "b-4", "name": "Charizard", "localId": "4"},
                ],
                {},
            ),
            (200, a, {}),
            (200, b, {}),
            (200, [], {}),
        ]
        with patch.object(mm, "_json_get", side_effect=responses):
            result = mm.resolve_tcgdex_card(target)
        self.assertEqual(result.status, "AMBIGUOUS")

    def test_denominator_conflict_never_resolves(self):
        target = lot(reference="4/130")
        detail = tcgdex_card(official=102, total=102)
        responses = [
            (200, [{"id": "base1-4", "name": "Charizard", "localId": "4"}], {}),
            (200, detail, {}),
            (200, [{"id": "base1", "name": "Base Set"}], {}),
            (200, detail, {}),
        ]
        with patch.object(mm, "_json_get", side_effect=responses):
            result = mm.resolve_tcgdex_card(target)
        self.assertEqual(result.status, "NO_MATCH")

    def test_canonical_enrichment_does_not_replace_listing_title(self):
        target = lot(name="Charizard")
        result = mm.CanonicalCard(
            "EXACT",
            card_id="base1-4",
            set_id="base1",
            set_name="Base Set",
            local_id="4",
            full_number="4/102",
            name="Charizard",
            language_code="en",
            reason="exact",
        )
        mm._attach_canonical_to_lot(target, result)
        self.assertEqual(target.title, "Charizard")
        self.assertEqual(target.card_set, "Base Set")
        self.assertEqual(target.set_family, "base1")


class RawMarketSignalTests(unittest.TestCase):
    def setUp(self):
        mm._DIAGNOSTICS = mm.MultiMarketDiagnostics()

    def test_exact_holo_uses_variant_specific_raw_prices(self):
        target = lot()
        target.variant = "Holo"
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
                "cardmarket": {
                    "trend-holo": 100,
                    "avg7-holo": 98,
                    "avg30-holo": 96,
                },
                "tcgplayer": {
                    "unit": "USD",
                    "holo": {"marketPrice": 110},
                },
            },
            variants={"normal": False, "holo": True, "reverse": False},
        )
        with patch.object(mm, "_usd_per_eur", return_value=1.1):
            signal = mm.raw_market_signal(target, canonical)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.variant, "holo")
        self.assertIn("Cardmarket", signal.sources)
        self.assertIn("TCGplayer", signal.sources)

    def test_ambiguous_variant_uses_conservative_manual_envelope(self):
        target = lot()
        canonical = mm.CanonicalCard(
            "EXACT",
            card_id="x",
            set_id="s",
            set_name="Set",
            local_id="4",
            full_number="4/102",
            name="Charizard",
            language_code="en",
            pricing={
                "cardmarket": {"trend": 50, "trend-holo": 100},
                "tcgplayer": {
                    "unit": "USD",
                    "normal": {"marketPrice": 55},
                    "holo": {"marketPrice": 110},
                },
            },
            variants={"normal": True, "holo": True, "reverse": False},
        )
        with patch.object(mm, "_usd_per_eur", return_value=1.0):
            signal = mm.raw_market_signal(target, canonical)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.variant, "AMBIGUOUS_CONSERVATIVE_ENVELOPE")
        self.assertLess(signal.low, signal.central)
        self.assertEqual(mm._DIAGNOSTICS.raw_signal_variant_ambiguous, 1)

    def test_raw_signal_never_constructs_graded_opportunity(self):
        target = lot(price=20)
        signal = mm.RawMarketSignal(
            60, 70, 80, "EUR", ("Cardmarket",), "holo", "manual"
        )
        review, gap = mm._should_manual_review(target, signal)
        self.assertTrue(review)
        self.assertGreater(gap, 60)


class PokeTraceExactGradedTests(unittest.TestCase):
    def setUp(self):
        mm._DIAGNOSTICS = mm.MultiMarketDiagnostics()
        self.target = lot()
        self.canonical = mm.CanonicalCard(
            "EXACT",
            card_id="base1-4",
            set_id="base1",
            set_name="Base Set",
            local_id="4",
            full_number="4/102",
            name="Charizard",
            language_code="en",
            unique_name_number=True,
        )

    def _responses(self, tier="PSA_8", sale_count=5, game="pokemon"):
        return [
            (
                200,
                {
                    "data": {
                        "active": True,
                        "user": {"plan": "Pro", "remaining": 9000, "limit": 10000},
                    }
                },
                {},
            ),
            (
                200,
                {
                    "data": [
                        {
                            "id": "pt-1",
                            "name": "Charizard",
                            "cardNumber": "4/102",
                            "set": {"name": "Base Set", "slug": "base-set"},
                            "variant": "Holofoil",
                            "productType": "single",
                            "game": game,
                            "currency": "USD",
                            "prices": {
                                "ebay": {
                                    tier: {
                                        "avg": 100,
                                        "low": 90,
                                        "high": 110,
                                        "saleCount": sale_count,
                                        "approxSaleCount": True,
                                    }
                                }
                            },
                        }
                    ]
                },
                {},
            ),
        ]

    def test_exact_psa8_poketrace_can_be_strong(self):
        budget = mm.RequestBudget()
        with patch.object(mm, "POKETRACE_ENABLED", True), patch.object(
            mm, "POKETRACE_API_KEY", "test-key"
        ), patch.object(
            mm, "_paced_poketrace_get", side_effect=self._responses()
        ), patch.object(mm, "_usd_per_eur", return_value=1.0):
            evidence = mm._poketrace_evidence(
                self.target, self.canonical, budget, NOW
            )
        self.assertEqual(evidence.status, watcher.EXTERNAL_MATCHED)
        self.assertEqual(evidence.strength, watcher.EVIDENCE_STRONG)
        self.assertEqual(evidence.source, "poketrace")
        self.assertEqual(evidence.estimate.central, 100)

    def test_poketrace_two_sales_stays_weak_by_default(self):
        budget = mm.RequestBudget()
        with patch.object(mm, "POKETRACE_ENABLED", True), patch.object(
            mm, "POKETRACE_API_KEY", "test-key"
        ), patch.object(
            mm, "_paced_poketrace_get",
            side_effect=self._responses(sale_count=2),
        ), patch.object(mm, "_usd_per_eur", return_value=1.0):
            evidence = mm._poketrace_evidence(
                self.target, self.canonical, budget, NOW
            )
        self.assertEqual(evidence.status, watcher.EXTERNAL_CLEAN_INSUFFICIENT)
        self.assertEqual(evidence.strength, watcher.EVIDENCE_WEAK)

    def test_psa_half_grade_tier_uses_underscore(self):
        self.target.grade = "8.5"
        self.assertEqual(mm._poketrace_grade_tier(self.target), "PSA_8_5")

    def test_french_us_record_is_not_exact_graded_evidence(self):
        self.target.language = "French"
        candidate = {
            "name": "Charizard",
            "cardNumber": "4/102",
            "set": {"name": "Base Set"},
            "variant": "Holofoil",
            "productType": "single",
            "game": "pokemon",
        }
        self.assertFalse(
            mm._candidate_exact_for_canonical(
                self.target, self.canonical, candidate
            )
        )

    def test_free_plan_never_creates_graded_evidence(self):
        budget = mm.RequestBudget()
        response = (
            200,
            {
                "data": {
                    "active": True,
                    "user": {"plan": "Free", "remaining": 200, "limit": 250},
                }
            },
            {},
        )
        with patch.object(mm, "POKETRACE_ENABLED", True), patch.object(
            mm, "POKETRACE_API_KEY", "test-key"
        ), patch.object(mm, "_paced_poketrace_get", return_value=response):
            evidence = mm._poketrace_evidence(
                self.target, self.canonical, budget, NOW
            )
        self.assertNotEqual(evidence.strength, watcher.EVIDENCE_STRONG)


class MultiMarketIntegrationTests(unittest.TestCase):
    def setUp(self):
        mm._DIAGNOSTICS = mm.MultiMarketDiagnostics()
        self.target = lot(price=40)
        self.gcc = watcher.GccMarketEvidence(
            self.target,
            [],
            None,
            None,
            watcher.GCC_BRANCH_UNAVAILABLE,
            watcher.EVIDENCE_UNAVAILABLE,
            rejection="historique vide",
            rejection_category=watcher.REJECTION_EMPTY_HISTORY,
            terminal=False,
        )
        self.candidate = watcher.ValuationCandidate(self.gcc)
        self.canonical = mm.CanonicalCard(
            "EXACT",
            card_id="base1-4",
            set_id="base1",
            set_name="Base Set",
            local_id="4",
            full_number="4/102",
            name="Charizard",
            language_code="en",
            unique_name_number=True,
        )

    def test_strong_poketrace_can_rescue_empty_gcc(self):
        evidence = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(self.target),
            watcher.EXTERNAL_MATCHED,
            watcher.EVIDENCE_STRONG,
            "poketrace",
            estimate=market_estimate(90, 100, 110),
            note="PokeTrace exact PSA 8",
            fetched_at=NOW,
        )
        with patch.object(mm, "_canonical_from_lot", return_value=self.canonical), patch.object(
            mm, "raw_market_signal", return_value=None
        ), patch.object(mm, "_poketrace_evidence", return_value=evidence):
            result = mm.multimarket_process_external_market_candidates(
                None,
                [self.candidate],
                {},
                watcher.ValidationBudgets(),
                watcher.RunDiagnostics(),
                NOW,
            )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].valuation_path, watcher.PATH_EXTERNAL_RESCUE)
        self.assertAlmostEqual(result[0].estimated_market, 100)

    def test_all_candidates_use_external_provider_even_when_gcc_supported(self):
        estimate = market_estimate(90, 100, 110)
        supported_op = watcher._opportunity_from_estimate(
            self.target, estimate, []
        )
        supported = watcher.GccMarketEvidence(
            self.target,
            [],
            estimate,
            supported_op,
            watcher.GCC_BRANCH_SUPPORTED,
            watcher.EVIDENCE_STRONG,
        )
        candidate = watcher.ValuationCandidate(supported)
        evidence = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(self.target),
            watcher.EXTERNAL_MATCHED,
            watcher.EVIDENCE_STRONG,
            "poketrace",
            estimate=market_estimate(92, 102, 112),
            note="external",
            fetched_at=NOW,
        )
        with patch.object(mm, "_canonical_from_lot", return_value=self.canonical), patch.object(
            mm, "raw_market_signal", return_value=None
        ), patch.object(mm, "_poketrace_evidence", return_value=evidence):
            result = mm.multimarket_process_external_market_candidates(
                None,
                [candidate],
                {},
                watcher.ValidationBudgets(),
                watcher.RunDiagnostics(),
                NOW,
            )
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0].valuation_path, watcher.PATH_GCC_EXTERNAL_CONFIRMED
        )

    def test_raw_only_interesting_card_becomes_manual_review_not_opportunity(self):
        raw = mm.RawMarketSignal(
            90, 100, 110, "EUR", ("Cardmarket",), "holo", "raw"
        )
        poketrace = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(self.target),
            watcher.EXTERNAL_CLEAN_NO_MATCH,
            watcher.EVIDENCE_UNAVAILABLE,
            "poketrace",
            note="graded absent",
            fetched_at=NOW,
        )
        fallback = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(self.target),
            watcher.EXTERNAL_TRANSIENT_UNAVAILABLE,
            watcher.EVIDENCE_UNAVAILABLE,
            "psa",
            note="APR unavailable; eBay 0",
            fetched_at=NOW,
        )
        state = {}
        with patch.object(mm, "_canonical_from_lot", return_value=self.canonical), patch.object(
            mm, "raw_market_signal", return_value=raw
        ), patch.object(mm, "_poketrace_evidence", return_value=poketrace), patch.object(
            mm, "_fallback_external", return_value=fallback
        ), patch.object(mm, "_notify_manual_review") as notify:
            result = mm.multimarket_process_external_market_candidates(
                None,
                [self.candidate],
                state,
                watcher.ValidationBudgets(),
                watcher.RunDiagnostics(),
                NOW,
            )
        self.assertEqual(result, [])
        notify.assert_called_once()
        self.assertIn(mm.MANUAL_REVIEW_STATE_KEY, state)

    def test_manual_review_is_deduplicated_inside_ttl(self):
        raw = mm.RawMarketSignal(
            90, 100, 110, "EUR", ("Cardmarket",), "holo", "raw"
        )
        lead = mm.ManualReviewLead(
            "key", self.target, self.canonical, raw, 55, "graded unavailable"
        )
        state = {}
        self.assertTrue(mm._manual_review_should_notify(state, lead, NOW))
        self.assertFalse(mm._manual_review_should_notify(state, lead, NOW))

    def test_install_bumps_external_cache_schema_and_wires_pipeline(self):
        old_inspect = watcher.inspect_item
        old_valid = watcher.is_valid_pokemon_card
        old_process = watcher.process_external_market_candidates
        old_schema = watcher.EXTERNAL_CACHE_SCHEMA_VERSION
        try:
            mm.install_canonical_multimarket_pipeline()
            self.assertEqual(
                watcher.EXTERNAL_CACHE_SCHEMA_VERSION,
                mm.MULTIMARKET_EXTERNAL_CACHE_SCHEMA_VERSION,
            )
            self.assertIs(watcher.inspect_item, mm.canonical_inspect_item)
            self.assertIs(
                watcher.process_external_market_candidates,
                mm.multimarket_process_external_market_candidates,
            )
        finally:
            watcher.inspect_item = old_inspect
            watcher.is_valid_pokemon_card = old_valid
            watcher.process_external_market_candidates = old_process
            watcher.EXTERNAL_CACHE_SCHEMA_VERSION = old_schema


if __name__ == "__main__":
    unittest.main()
