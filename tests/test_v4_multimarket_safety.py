from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import watcher
import v4_canonical_multimarket as mm
import v4_multimarket_safety as safety


NOW = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)


def lot(*, variant="", language="English", price=40.0):
    return watcher.Lot(
        url="https://gradedcardcenter.com/item/safety",
        title="Charizard",
        current_price=price,
        source_type="fixed",
        grader="PSA",
        grade="8",
        card_number="4/102",
        card_set="Base Set",
        language=language,
        variant=variant,
        body=(
            "Catégorie: Pokémon\n"
            "Référence: #4/102\n"
            "Série: Base Set\n"
            f"Langue: {language}\n"
            "Article Gradation Détails\n"
            "Société de gradation: PSA\n"
            "Note: 8\n"
            + (f"Variante: {variant}\n" if variant else "")
        ),
    )


def canonical(*, variants=None, unique=True):
    return mm.CanonicalCard(
        "EXACT",
        card_id="base1-4",
        set_id="base1",
        set_name="Base Set",
        local_id="4",
        full_number="4/102",
        name="Charizard",
        language_code="en",
        variants=variants
        if variants is not None
        else {"normal": False, "holo": True, "reverse": False, "firstEdition": False},
        unique_name_number=unique,
    )


def candidate(*, number="004/102", variant="Holofoil", set_name="Base Set"):
    return {
        "id": "pt-1",
        "name": "Charizard",
        "cardNumber": number,
        "set": {"name": set_name, "slug": "base-set"},
        "variant": variant,
        "rarity": "Rare Holo",
        "productType": "single",
        "game": "pokemon",
    }


def gcc_candidate(target):
    evidence = watcher.GccMarketEvidence(
        target,
        [],
        None,
        None,
        watcher.GCC_BRANCH_UNAVAILABLE,
        watcher.EVIDENCE_UNAVAILABLE,
        rejection="historique vide",
        rejection_category=watcher.REJECTION_EMPTY_HISTORY,
        terminal=False,
    )
    return watcher.ValuationCandidate(evidence)


def external(status, *, strength=None, source="poketrace", estimate=None, note=""):
    target = lot()
    return watcher.ExternalMarketEvidence(
        watcher.external_commercial_identity_key(target),
        status,
        strength or watcher.EVIDENCE_UNAVAILABLE,
        source,
        estimate=estimate,
        note=note,
        fetched_at=NOW,
    )


def strong_estimate():
    return watcher.MarketEstimate(
        low=90,
        central=100,
        high=110,
        kept_comparables=[],
        rejected_outliers=[],
        recent_90_count=0,
        dated_count=0,
        liquidity="moyenne",
        dispersion="faible",
        confidence="moyenne",
        adaptive_discount_pct=30,
        rationale="strong external",
        source_counts={"external": 5},
        exact_grade_count=5,
        same_grader_count=5,
        source_consistent=True,
    )


class ProviderIdentityHardeningTests(unittest.TestCase):
    def test_numeric_leading_zero_number_is_deterministically_equivalent(self):
        self.assertTrue(
            safety.hardened_candidate_exact_for_canonical(
                lot(variant="Holo"), canonical(), candidate(number="004/102")
            )
        )

    def test_denominator_conflict_is_rejected(self):
        self.assertFalse(
            safety.hardened_candidate_exact_for_canonical(
                lot(variant="Holo"), canonical(), candidate(number="4/130")
            )
        )

    def test_provider_first_edition_never_manufactures_listing_edition(self):
        premium = candidate(variant="1st Edition Holofoil")
        self.assertFalse(
            safety.hardened_candidate_exact_for_canonical(
                lot(),
                canonical(
                    variants={
                        "normal": False,
                        "holo": True,
                        "reverse": False,
                        "firstEdition": True,
                    }
                ),
                premium,
            )
        )

    def test_catalog_first_edition_applicable_blocks_unknown_listing_edition(self):
        self.assertFalse(
            safety.hardened_candidate_exact_for_canonical(
                lot(),
                canonical(
                    variants={
                        "normal": False,
                        "holo": True,
                        "reverse": False,
                        "firstEdition": True,
                    }
                ),
                candidate(),
            )
        )

    def test_provider_holo_can_be_used_when_catalog_has_only_holo(self):
        self.assertTrue(
            safety.hardened_candidate_exact_for_canonical(
                lot(), canonical(), candidate()
            )
        )

    def test_unknown_listing_finish_blocks_when_catalog_has_multiple_finishes(self):
        self.assertFalse(
            safety.hardened_candidate_exact_for_canonical(
                lot(),
                canonical(
                    variants={
                        "normal": True,
                        "holo": True,
                        "reverse": False,
                        "firstEdition": False,
                    }
                ),
                candidate(),
            )
        )

    def test_unique_bridge_requires_full_provider_denominator(self):
        self.assertFalse(
            safety.hardened_candidate_exact_for_canonical(
                lot(variant="Holo"),
                canonical(unique=True),
                candidate(number="4", set_name="Different Provider Set"),
            )
        )

    def test_same_card_number_normalization_helpers(self):
        self.assertTrue(safety._same_card_number("004/102", "4/102"))
        self.assertTrue(safety._same_card_number("04", "4"))
        self.assertTrue(safety._same_card_number("TG04/TG30", "TG04/TG30"))
        self.assertFalse(safety._same_card_number("004/102", "4/130"))
        self.assertFalse(safety._same_card_number("004/102", "5/102"))


class ProviderFailureSemanticsTests(unittest.TestCase):
    def setUp(self):
        mm._DIAGNOSTICS = mm.MultiMarketDiagnostics()
        mm.clear_tcgdex_cache()
        self.target = lot(variant="Holo")
        self.candidate = gcc_candidate(self.target)
        self.canonical = canonical()

    def run_pipeline(self, poketrace, fallback):
        state = {}
        diagnostics = watcher.RunDiagnostics()
        with patch.object(mm, "_canonical_from_lot", return_value=self.canonical), patch.object(
            mm, "raw_market_signal", return_value=None
        ), patch.object(mm, "_poketrace_evidence", return_value=poketrace), patch.object(
            mm, "_fallback_external", return_value=fallback
        ):
            result = safety.hardened_multimarket_process_external_market_candidates(
                None,
                [self.candidate],
                state,
                watcher.ValidationBudgets(),
                diagnostics,
                NOW,
            )
        return result, state, diagnostics

    def test_poketrace_transient_is_not_hidden_by_clean_fallback(self):
        poketrace = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(self.target),
            watcher.EXTERNAL_TRANSIENT_UNAVAILABLE,
            watcher.EVIDENCE_UNAVAILABLE,
            "poketrace",
            note="HTTP 503",
            fetched_at=NOW,
        )
        fallback = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(self.target),
            watcher.EXTERNAL_CLEAN_NO_MATCH,
            watcher.EVIDENCE_UNAVAILABLE,
            "ebay",
            note="0 comps",
            fetched_at=NOW,
        )
        result, state, diagnostics = self.run_pipeline(poketrace, fallback)
        self.assertEqual(result, [])
        self.assertNotIn(watcher.EXTERNAL_CACHE_STATE_KEY, state)
        self.assertEqual(
            diagnostics.rejection_count(watcher.REJECTION_EXTERNAL_RETRY), 1
        )

    def test_poketrace_rate_limit_is_not_cached_after_weak_fallback(self):
        poketrace = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(self.target),
            watcher.EXTERNAL_RATE_LIMITED,
            watcher.EVIDENCE_UNAVAILABLE,
            "poketrace",
            note="429",
            fetched_at=NOW,
        )
        fallback = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(self.target),
            watcher.EXTERNAL_CLEAN_INSUFFICIENT,
            watcher.EVIDENCE_WEAK,
            "ebay",
            note="1 comp",
            fetched_at=NOW,
        )
        _result, state, _diagnostics = self.run_pipeline(poketrace, fallback)
        self.assertNotIn(watcher.EXTERNAL_CACHE_STATE_KEY, state)

    def test_strong_apr_ebay_fallback_can_complete_during_poketrace_outage(self):
        poketrace = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(self.target),
            watcher.EXTERNAL_TRANSIENT_UNAVAILABLE,
            watcher.EVIDENCE_UNAVAILABLE,
            "poketrace",
            note="503",
            fetched_at=NOW,
        )
        fallback = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(self.target),
            watcher.EXTERNAL_MATCHED,
            watcher.EVIDENCE_STRONG,
            "ebay",
            estimate=strong_estimate(),
            note="exact sold comps",
            fetched_at=NOW,
        )
        result, state, _diagnostics = self.run_pipeline(poketrace, fallback)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].valuation_path, watcher.PATH_EXTERNAL_RESCUE)
        self.assertIn(watcher.EXTERNAL_CACHE_STATE_KEY, state)

    def test_poketrace_budget_pending_still_allows_strong_fallback(self):
        poketrace = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(self.target),
            watcher.EXTERNAL_PENDING,
            watcher.EVIDENCE_UNAVAILABLE,
            "poketrace",
            note="budget",
            fetched_at=NOW,
        )
        fallback = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(self.target),
            watcher.EXTERNAL_MATCHED,
            watcher.EVIDENCE_STRONG,
            "psa",
            estimate=strong_estimate(),
            note="APR exact",
            fetched_at=NOW,
        )
        result, _state, _diagnostics = self.run_pipeline(poketrace, fallback)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].valuation_path, watcher.PATH_EXTERNAL_RESCUE)


class ManualReviewNotificationTests(unittest.TestCase):
    def test_unicode_title_is_rfc2047_encoded(self):
        target = lot(price=20)
        lead = mm.ManualReviewLead(
            "key",
            target,
            canonical(),
            mm.RawMarketSignal(
                60, 70, 80, "EUR", ("Cardmarket",), "holo", "raw"
            ),
            66.7,
            "graded unavailable",
        )
        response = Mock()
        response.raise_for_status.return_value = None
        with patch.object(watcher, "NTFY_TOPIC", "test-topic"), patch.object(
            safety.requests, "post", return_value=response
        ) as post:
            safety.safe_notify_manual_review(lead)
        title = post.call_args.kwargs["headers"]["Title"]
        self.assertTrue(title.startswith("=?utf-8?"))


class InstallTests(unittest.TestCase):
    def test_safety_installer_wires_hardened_process_and_provider_match(self):
        old_process = watcher.process_external_market_candidates
        old_candidate = mm._candidate_exact_for_canonical
        old_notify = mm._notify_manual_review
        try:
            safety.install_multimarket_safety_hardening()
            self.assertIs(
                watcher.process_external_market_candidates,
                safety.hardened_multimarket_process_external_market_candidates,
            )
            self.assertIs(
                mm._candidate_exact_for_canonical,
                safety.hardened_candidate_exact_for_canonical,
            )
            self.assertIs(mm._notify_manual_review, safety.safe_notify_manual_review)
        finally:
            watcher.process_external_market_candidates = old_process
            mm._candidate_exact_for_canonical = old_candidate
            mm._notify_manual_review = old_notify


if __name__ == "__main__":
    unittest.main()
