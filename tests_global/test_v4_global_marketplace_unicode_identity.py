from __future__ import annotations

import unittest
from unittest import mock

import v4_global_market_core as core
import v4_global_marketplace_unicode_identity as unicode_identity


class GlobalUnicodeIdentityTests(unittest.TestCase):
    def test_latin_normalization_contract_is_unchanged(self):
        values = (
            "Mewtwo",
            "Pokémon Card 151",
            "S-P Promotional",
            "Team Rocket's Meowth",
            "Édition 1",
            "SV8a",
        )
        for value in values:
            self.assertEqual(
                unicode_identity._unicode_identity_norm(value),
                unicode_identity._ORIGINAL_NORM(value),
            )

    def test_exact_japanese_identity_becomes_complete_without_translation(self):
        with mock.patch.object(core, "_norm", unicode_identity._unicode_identity_norm):
            identity = core.CommercialIdentity(
                name="ミュウツー",
                set_name="ポケモンカード151",
                number="183/165",
                language="ja",
                grader="PSA",
                grade="10",
            )
            self.assertTrue(identity.complete_for_exact_market)
            self.assertTrue(identity.opportunity_language)
            self.assertIn("ミュウツー", identity.strict_key)
            self.assertIn("ポケモンカード151", identity.strict_key)

    def test_japanese_names_do_not_collapse_to_one_blank_key(self):
        with mock.patch.object(core, "_norm", unicode_identity._unicode_identity_norm):
            mewtwo = core.CommercialIdentity(
                "ミュウツー", "ポケモンカード151", "183/165", "ja", "PSA", "10"
            )
            pikachu = core.CommercialIdentity(
                "ピカチュウ", "ポケモンカード151", "173/165", "ja", "PSA", "10"
            )
            self.assertNotEqual(mewtwo.strict_key, pikachu.strict_key)


if __name__ == "__main__":
    unittest.main()
