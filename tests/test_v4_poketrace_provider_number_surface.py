from __future__ import annotations

import unittest
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as mm
import v4_poketrace_market_retrieval as retrieval


def _lot(name: str, number: str, set_name: str) -> watcher.Lot:
    return watcher.Lot(
        url="https://gradedcardcenter.com/item/poketrace-padding-test",
        title=name,
        current_price=50.0,
        source_type="fixed",
        grader="PSA",
        grade="10",
        card_number=number,
        card_set=set_name,
        language="Japanese",
        body=(
            "Catégorie: Pokémon\n"
            f"Référence: #{number}\n"
            f"Série: {set_name}\n"
            "Langue: Japanese\n"
            "Société de gradation: PSA\n"
            "Note: 10\n"
        ),
    )


def _canonical(name: str, number: str, set_name: str, set_id: str) -> mm.CanonicalCard:
    return mm.CanonicalCard(
        "EXACT",
        card_id=f"{set_id}-{number.split('/', 1)[0]}",
        set_id=set_id,
        set_name=set_name,
        local_id=number.split("/", 1)[0],
        full_number=number,
        name=name,
        language_code="ja",
        reason="TCGDEX_EXACT_SET_LOCALID",
    )


class PokeTraceProviderNumberSurfaceTests(unittest.TestCase):
    def test_provider_number_preserves_padded_surface(self):
        self.assertEqual(retrieval._provider_card_number("#069/062"), "069/062")
        self.assertEqual(retrieval._provider_card_number("#109/098"), "109/098")
        self.assertEqual(retrieval._provider_card_number(" DP045 "), "DP045")

    def test_matching_normalizer_remains_numeric_safe_and_separate(self):
        self.assertEqual(retrieval._normalize_card_number("#069/062"), "69/62")
        self.assertEqual(retrieval._normalize_card_number("#109/098"), "109/98")

    def test_groudon_context_sends_provider_catalog_surface(self):
        lot = _lot("Groudon", "069/062", "Raging Surf")
        canonical = _canonical("Groudon", "069/062", "Raging Surf", "SV3a")
        context = retrieval._retrieval_context(lot, canonical)
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.card_number, "069/062")
        self.assertEqual(context.game, "pokemon-japanese")

    def test_team_rocket_meowth_context_preserves_denominator_padding(self):
        lot = _lot("Team Rocket's Meowth", "109/098", "Glory of the Team Rocket")
        canonical = _canonical(
            "Team Rocket's Meowth",
            "109/098",
            "Glory of the Team Rocket",
            "S12",
        )
        context = retrieval._retrieval_context(lot, canonical)
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.card_number, "109/098")

    def test_structured_get_does_not_strip_padding_before_provider_call(self):
        captured = []

        def fake_get(budget, url, *, params=None):
            captured.append(dict(params or {}))
            return 200, {"data": []}, {}

        context = retrieval.PokeTraceRetrievalContext(
            search_name="Groudon",
            card_number="069/062",
            game="pokemon-japanese",
            language_code="ja",
        )
        token = retrieval._ACTIVE_CONTEXT.set(context)
        try:
            with patch.object(retrieval, "_ORIGINAL_PACED_GET", side_effect=fake_get):
                retrieval._structured_paced_get(
                    mm.RequestBudget(),
                    f"{mm.POKETRACE_BASE_URL}/cards",
                    params={
                        "search": "Groudon 069/062",
                        "market": "US",
                        "limit": 20,
                        "product_type": "single",
                    },
                )
        finally:
            retrieval._ACTIVE_CONTEXT.reset(token)

        self.assertEqual(captured[0]["search"], "Groudon")
        self.assertEqual(captured[0]["card_number"], "069/062")
        self.assertEqual(captured[0]["game"], "pokemon-japanese")
        self.assertEqual(captured[0]["market"], "US")


if __name__ == "__main__":
    unittest.main()
