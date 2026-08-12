from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as mm
import v4_multimarket_safety as safety


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


def poketrace_payload():
    return {
        "data": [
            {
                "id": "pt-charizard-4",
                "name": "Charizard",
                "cardNumber": "4/102",
                "productType": "single",
                "game": "pokemon",
                "set": {"name": "Base Set"},
                "variant": "Holo",
                "currency": "USD",
                "prices": {
                    "ebay": {
                        "PSA 8": {
                            "avg": 100.0,
                            "low": 90.0,
                            "high": 110.0,
                            "saleCount": 6,
                        }
                    }
                },
            }
        ]
    }


class AdversarialQARedTest(unittest.TestCase):
    def setUp(self):
        mm._DIAGNOSTICS = mm.MultiMarketDiagnostics()
        mm.clear_tcgdex_cache()

    def test_same_name_number_multiple_sets_is_ambiguous(self):
        """Red Team Test 1: Multiple sets with same name+localId must be AMBIGUOUS without exact set."""
        target = lot(series="Unknown GCC Set")
        a = tcgdex_card(card_id="base1-4", set_id="base1", set_name="Base Set")
        b = tcgdex_card(card_id="base2-4", set_id="base2", set_name="Base Set 2")
        def mock_get(url, params=None, timeout=None):
            if "/cards/base1-4" in url:
                return 200, a, {}
            if "/cards/base2-4" in url:
                return 200, b, {}
            if params and params.get("localId") == "eq:4":
                return 200, [
                    {"id": "base1-4", "name": "Charizard", "localId": "4"},
                    {"id": "base2-4", "name": "Charizard", "localId": "4"},
                ], {}
            return 200, [], {}
        with patch.object(mm, "_json_get", side_effect=mock_get):
            result = mm.resolve_tcgdex_card(target)
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(mm._DIAGNOSTICS.tcgdex_ambiguous, 1)

        # Ensure ambiguous identity does NOT populate canonical fields on lot
        mm._attach_canonical_to_lot(target, result)
        self.assertFalse(hasattr(target, "tcgdex_card_id") and bool(target.tcgdex_card_id))

    def test_number_leading_zeros_stripped(self):
        """Red Team Test 2: #004/102 matches localId 4 when name, set and denominator agree."""
        target = lot(reference="#004/102")
        detail = tcgdex_card(local_id="4", official=102, total=102)
        def mock_get(url, params=None, timeout=None):
            if "/cards/" in url:
                return 200, detail, {}
            if params and params.get("localId") == "eq:4":
                return 200, [{"id": "base1-4", "name": "Charizard", "localId": "4"}], {}
            return 200, [], {}
        with patch.object(mm, "_json_get", side_effect=mock_get):
            result = mm.resolve_tcgdex_card(target)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "base1-4")
        self.assertEqual(result.local_id, "4")
        self.assertEqual(result.full_number, "4/102")

    def test_poketrace_evidence_transient_when_fx_unavailable(self):
        """Red Team Test 3: FX unavailability must be transient, not clean no-match or poisoned cache."""
        target = lot(price=40.0)
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
            reason="exact",
        )
        budget = mm.RequestBudget()
        budget.auth_checked = True
        budget.auth_ok = True

        # 1. When FX is unavailable (_usd_per_eur returns None)
        with patch.object(mm, "POKETRACE_ENABLED", True), patch.object(
            mm, "POKETRACE_API_KEY", "test-key"
        ), patch.object(
            mm, "_json_get", return_value=(200, poketrace_payload(), {})
        ), patch.object(mm, "_usd_per_eur", return_value=None):
            evidence = mm._poketrace_evidence(target, canonical, budget, NOW)

        self.assertEqual(evidence.status, watcher.EXTERNAL_TRANSIENT_UNAVAILABLE)
        self.assertEqual(evidence.strength, watcher.EVIDENCE_UNAVAILABLE)
        self.assertIn("conversion USD/EUR indisponible", evidence.note)

        # 2. Verify end-to-end pipeline handling with empty fallback
        gcc = watcher.GccMarketEvidence(
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
        candidate = watcher.ValuationCandidate(gcc)
        state = {}
        fallback_empty = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(target),
            watcher.EXTERNAL_CLEAN_NO_MATCH,
            watcher.EVIDENCE_UNAVAILABLE,
            "psa",
            note="APR empty; eBay empty",
            fetched_at=NOW,
        )

        with patch.object(mm, "POKETRACE_ENABLED", True), patch.object(
            mm, "POKETRACE_API_KEY", "test-key"
        ), patch.object(
            mm, "_canonical_from_lot", return_value=canonical
        ), patch.object(
            mm, "raw_market_signal", return_value=None
        ), patch.object(
            mm, "_poketrace_evidence", return_value=evidence
        ), patch.object(
            mm, "_fallback_external", return_value=fallback_empty
        ):
            opportunities = safety.hardened_multimarket_process_external_market_candidates(
                None,
                [candidate],
                state,
                watcher.ValidationBudgets(),
                watcher.RunDiagnostics(),
                NOW,
            )

        # No opportunity yet, but must NOT poison external cache with clean negative entry
        self.assertEqual(len(opportunities), 0)
        cache_key = watcher.external_commercial_identity_key(target)
        stored_cache = state.get("external_market_evidence", {}).get(cache_key)
        self.assertIsNone(stored_cache)

        # 3. Later successful retry when FX is restored
        budget_retry = mm.RequestBudget()
        budget_retry.auth_checked = True
        budget_retry.auth_ok = True
        with patch.object(mm, "POKETRACE_ENABLED", True), patch.object(
            mm, "POKETRACE_API_KEY", "test-key"
        ), patch.object(
            mm, "_json_get", return_value=(200, poketrace_payload(), {})
        ), patch.object(mm, "_usd_per_eur", return_value=1.0):
            retry_evidence = mm._poketrace_evidence(
                target, canonical, budget_retry, NOW
            )

        self.assertEqual(retry_evidence.status, watcher.EXTERNAL_MATCHED)
        self.assertEqual(retry_evidence.strength, watcher.EVIDENCE_STRONG)
        self.assertIsNotNone(retry_evidence.estimate)
        self.assertAlmostEqual(retry_evidence.estimate.central, 100.0)


if __name__ == "__main__":
    unittest.main()
