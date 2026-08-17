from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as mm
import v4_poketrace_market_retrieval as retrieval


NOW = datetime(2026, 8, 17, 15, 0, tzinfo=timezone.utc)


def _lot(
    *,
    name="Charizard",
    reference="4/102",
    language="English",
    grader="PSA",
    grade="10",
    series="Base Set",
):
    return watcher.Lot(
        url="https://gradedcardcenter.com/item/poketrace-retrieval-test",
        title=name,
        current_price=40.0,
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


def _canonical(
    *,
    name="Charizard",
    number="4/102",
    language_code="en",
    set_name="Base Set",
    set_id="base1",
):
    return mm.CanonicalCard(
        "EXACT",
        card_id=f"{set_id}-{number.split('/', 1)[0]}",
        set_id=set_id,
        set_name=set_name,
        local_id=number.split("/", 1)[0],
        full_number=number,
        name=name,
        language_code=language_code,
        reason="TCGDEX_EXACT_SET_LOCALID",
    )


def _candidate(
    *,
    name="Charizard",
    number="4/102",
    set_name="Base Set",
    game="pokemon",
    tier="PSA_10",
):
    return {
        "id": "pt-test-card",
        "name": name,
        "cardNumber": number,
        "set": {"name": set_name, "slug": "fixture-set"},
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
                    "saleCount": 5,
                    "approxSaleCount": True,
                }
            }
        },
    }


class StructuredPokeTraceRetrievalTests(unittest.TestCase):
    def setUp(self):
        mm._DIAGNOSTICS = mm.MultiMarketDiagnostics()

    def test_structured_get_replaces_only_retrieval_fields_for_english(self):
        calls = []

        def fake_get(budget, url, *, params=None):
            calls.append((budget, url, dict(params or {})))
            return 200, {"data": []}, {}

        context = retrieval.PokeTraceRetrievalContext(
            search_name="Charizard",
            card_number="4/102",
            game="pokemon",
            language_code="en",
        )
        token = retrieval._ACTIVE_CONTEXT.set(context)
        try:
            with patch.object(retrieval, "_ORIGINAL_PACED_GET", side_effect=fake_get):
                retrieval._structured_paced_get(
                    mm.RequestBudget(),
                    f"{mm.POKETRACE_BASE_URL}/cards",
                    params={
                        "search": "Charizard 4/102",
                        "market": "US",
                        "limit": 20,
                        "product_type": "single",
                    },
                )
        finally:
            retrieval._ACTIVE_CONTEXT.reset(token)

        params = calls[0][2]
        self.assertEqual(params["search"], "Charizard")
        self.assertEqual(params["card_number"], "4/102")
        self.assertEqual(params["game"], "pokemon")
        self.assertEqual(params["market"], "US")
        self.assertEqual(params["product_type"], "single")

    def test_japanese_retrieval_uses_pokemon_japanese_game(self):
        target = _lot(
            name="Lapras",
            reference="177/172",
            language="Japanese",
            series="VSTAR Universe",
        )
        canonical = _canonical(
            name="Lapras",
            number="177/172",
            language_code="ja",
            set_name="VSTAR Universe",
            set_id="S12a",
        )
        context = retrieval._retrieval_context(target, canonical)
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.search_name, "Lapras")
        self.assertEqual(context.card_number, "177/172")
        self.assertEqual(context.game, "pokemon-japanese")

    def test_number_normalization_matches_v5_structured_contract(self):
        self.assertEqual(retrieval._normalize_card_number("#004/102"), "4/102")
        self.assertEqual(retrieval._normalize_card_number("041"), "41")
        self.assertEqual(retrieval._normalize_card_number("DP045"), "dp45")
        self.assertEqual(retrieval._normalize_card_number("232/SV-P"), "232/sv-p")

    def test_french_is_skipped_without_spending_poketrace_budget(self):
        target = _lot(language="French")
        canonical = _canonical(language_code="fr")
        budget = mm.RequestBudget()

        def forbidden(*_args, **_kwargs):
            raise AssertionError("unsupported exact-market language must not call PokeTrace")

        with patch.object(retrieval, "_ORIGINAL_EVIDENCE", side_effect=forbidden):
            evidence = retrieval._structured_poketrace_evidence(
                target, canonical, budget, NOW
            )

        self.assertEqual(evidence.status, watcher.EXTERNAL_CLEAN_NO_MATCH)
        self.assertEqual(evidence.source, "poketrace")
        self.assertEqual(budget.poketrace_requests, 0)
        self.assertEqual(mm._DIAGNOSTICS.poketrace_attempted, 0)
        self.assertIn("non applicable", evidence.note)

    def test_real_v4_acceptance_runs_after_structured_english_retrieval(self):
        target = _lot()
        canonical = _canonical()
        budget = mm.RequestBudget()
        calls = []
        responses = [
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
            (200, {"data": [_candidate()]}, {}),
        ]

        def fake_get(_budget, url, *, params=None):
            calls.append((url, dict(params or {})))
            return responses.pop(0)

        with patch.object(mm, "POKETRACE_ENABLED", True), patch.object(
            mm, "POKETRACE_API_KEY", "offline-placeholder"
        ), patch.object(mm, "_usd_per_eur", return_value=1.0), patch.object(
            retrieval, "_ORIGINAL_PACED_GET", side_effect=fake_get
        ), patch.object(
            mm, "_paced_poketrace_get", retrieval._structured_paced_get
        ):
            evidence = retrieval._structured_poketrace_evidence(
                target, canonical, budget, NOW
            )

        self.assertEqual(evidence.status, watcher.EXTERNAL_MATCHED)
        self.assertEqual(evidence.strength, watcher.EVIDENCE_STRONG)
        card_params = calls[1][1]
        self.assertEqual(card_params["search"], "Charizard")
        self.assertEqual(card_params["card_number"], "4/102")
        self.assertEqual(card_params["game"], "pokemon")
        self.assertEqual(mm._DIAGNOSTICS.poketrace_exact, 1)

    def test_structured_retrieval_does_not_relax_wrong_set_gate(self):
        target = _lot()
        canonical = _canonical()
        budget = mm.RequestBudget()
        responses = [
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
            (200, {"data": [_candidate(set_name="Jungle")]}, {}),
        ]

        def fake_get(_budget, _url, *, params=None):
            return responses.pop(0)

        with patch.object(mm, "POKETRACE_ENABLED", True), patch.object(
            mm, "POKETRACE_API_KEY", "offline-placeholder"
        ), patch.object(
            retrieval, "_ORIGINAL_PACED_GET", side_effect=fake_get
        ), patch.object(
            mm, "_paced_poketrace_get", retrieval._structured_paced_get
        ):
            evidence = retrieval._structured_poketrace_evidence(
                target, canonical, budget, NOW
            )

        self.assertEqual(evidence.status, watcher.EXTERNAL_CLEAN_NO_MATCH)
        self.assertEqual(mm._DIAGNOSTICS.poketrace_exact, 0)
        self.assertEqual(mm._DIAGNOSTICS.poketrace_no_match, 1)

    def test_installer_is_idempotent(self):
        old_evidence = mm._poketrace_evidence
        old_get = mm._paced_poketrace_get
        old_installed = retrieval._INSTALLED
        try:
            retrieval._INSTALLED = False
            retrieval.install_v4_poketrace_market_retrieval()
            first_evidence = mm._poketrace_evidence
            first_get = mm._paced_poketrace_get
            retrieval.install_v4_poketrace_market_retrieval()
            self.assertIs(mm._poketrace_evidence, first_evidence)
            self.assertIs(mm._paced_poketrace_get, first_get)
            self.assertIs(first_evidence, retrieval._structured_poketrace_evidence)
            self.assertIs(first_get, retrieval._structured_paced_get)
        finally:
            mm._poketrace_evidence = old_evidence
            mm._paced_poketrace_get = old_get
            retrieval._INSTALLED = old_installed


if __name__ == "__main__":
    unittest.main()
