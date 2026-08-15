from __future__ import annotations

import json
import unittest
from dataclasses import asdict

from v5 import source_scout_benchmark as scout
from v5 import source_scout_opportunity_ppt_validation as target
from v5.models import CardIdentity


class OpportunityPptValidationTests(unittest.TestCase):
    def test_budget_is_bounded_and_cmapi_is_absent(self) -> None:
        self.assertLessEqual(target.PPT_CALL_CAP, 60)
        self.assertGreaterEqual(target.PPT_INTERVAL_SECONDS, 2.2)

    def test_fr_copy_is_anchor_not_exact(self) -> None:
        source = scout.Observation("pokemonpricetracker", "EN")
        source.identity = "EXACT"
        source.variant = "EXACT"
        source.language = "EXACT"
        source.raw_usd = 10.0
        source.raw_eur = 9.0
        source.psa10_usd = 30.0
        source.graded_available = True
        source.history = "180D_RETURNED"
        source.liquidity = 7
        card = scout.PanelCard(
            identity=CardIdentity(
                game="Pokémon TCG",
                card_name="Noctali VMAX",
                set="Évolution Céleste",
                card_number="215",
                language="fr",
                finish="Holo",
            ),
            tcgdex_id="swsh7-215",
            tcgdex_language="fr",
            marketplace="TEST",
        )
        copied = target._copy_anchor(source, card)
        self.assertEqual(copied.identity, "ANCHOR_ONLY")
        self.assertEqual(copied.language, "NOT_EXPOSED")
        self.assertEqual(copied.raw_eur, 9.0)
        self.assertEqual(copied.psa10_usd, 30.0)
        self.assertTrue(copied.graded_available)
        self.assertEqual(copied.history, "180D_RETURNED")

    def test_observation_serializes_as_json_report_row(self) -> None:
        row = scout.Observation("pokemonpricetracker", "Umbreon VMAX")
        row.identity = "EXACT"
        row.psa10_usd = 123.45
        encoded = json.dumps(asdict(row))
        self.assertIn('"identity": "EXACT"', encoded)
        self.assertIn('"psa10_usd": 123.45', encoded)


if __name__ == "__main__":
    unittest.main()
