from __future__ import annotations

import unittest

from v5 import source_scout_opportunity_benchmark as benchmark
from v5.models import CardIdentity
from v5.source_scout_benchmark import PanelCard


class OpportunityBenchmarkTests(unittest.TestCase):
    def test_panel_is_en_fr_pairs_and_budget_is_safe(self) -> None:
        self.assertEqual(benchmark.LANGUAGES, ("en", "fr"))
        self.assertEqual(benchmark.UNIQUE_PRINT_TARGET, 12)
        self.assertEqual(benchmark.CMAPI_MAX_CALLS, 50)
        self.assertGreaterEqual(benchmark.CMAPI_STOP_REMAINING, 40)
        self.assertEqual(len(set(benchmark.CANDIDATE_TCGDEX_IDS)), len(benchmark.CANDIDATE_TCGDEX_IDS))

    def test_cmapi_fr_observation_uses_fr_specific_cardmarket_field(self) -> None:
        card = PanelCard(
            identity=CardIdentity(
                game="Pokémon TCG",
                card_name="Noctali VMAX",
                set="Évolution Céleste",
                card_number="215",
                language="fr",
            ),
            tcgdex_id="swsh7-215",
            tcgdex_language="fr",
            marketplace="TEST",
        )
        row = {
            "prices": {
                "cardmarket": {
                    "lowest_near_mint": 1500,
                    "lowest_near_mint_FR": 3000,
                },
                "ebay": {
                    "currency": "USD",
                    "graded": {"psa": {"10": {"median_price": 3400, "sample_size": 5}}},
                },
            }
        }
        obs = benchmark._current_cmapi_observation(card, row, fr_anchor=True)
        self.assertEqual(obs.identity, "ANCHOR_ONLY")
        self.assertEqual(obs.language, "EXACT")
        self.assertEqual(obs.raw_eur, 3000)
        self.assertEqual(obs.psa10_usd, 3400)


if __name__ == "__main__":
    unittest.main()
