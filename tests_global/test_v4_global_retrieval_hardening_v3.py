import unittest

import japan_edge_hunter as japan
from v4_global_retrieval_hardening_v3 import (
    comc_text_row_proof_v3,
    fanatics_title_identity_proof_v3,
    magi_identity_check_v3,
)


GROUDON = japan.Identity(
    name="Groudon",
    set_name="Raging Surf",
    number="69/62",
    language="Japanese",
    grader="PSA",
    grade="10",
    year=2023,
)
MEWTWO = japan.Identity(
    name="Mewtwo",
    set_name="151",
    number="183/165",
    language="Japanese",
    grader="PSA",
    grade="10",
    year=2023,
)
PIKACHU = japan.Identity(
    name="Pikachu",
    set_name="M-P Promotional",
    number="20/M-P",
    language="Japanese",
    grader="PSA",
    grade="10",
    year=2025,
)


class RetrievalHardeningV3Tests(unittest.TestCase):
    def test_fanatics_h1_exact_not_poisoned_by_unrelated_page_fraction(self):
        title = "2023 Pokemon Japanese Scarlet & Violet Raging Surf AR Groudon #69 PSA 10 GEM MINT"
        ok, proof = fanatics_title_identity_proof_v3(title, GROUDON)
        self.assertTrue(ok)
        self.assertEqual(proof, "EXACT_FANATICS_H1_SET_LOCAL_ID_PROOF")

    def test_fanatics_wrong_fraction_in_h1_still_blocks(self):
        title = "2023 Pokemon Japanese Scarlet & Violet Raging Surf AR Groudon #69 69/70 PSA 10 GEM MINT"
        ok, reason = fanatics_title_identity_proof_v3(title, GROUDON)
        self.assertFalse(ok)
        self.assertEqual(reason, "conflicting_full_fraction")

    def test_magi_title_1_card_ignores_related_2_card_boilerplate(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/1",
            "[PSA10] Mewtwo 183/165 1枚 日本",
            10000,
            "151 Japanese Mewtwo 183/165 PSA10 related recommendation 2枚",
        )
        ok, proof = magi_identity_check_v3(ask, MEWTWO)
        self.assertTrue(ok)
        self.assertEqual(proof, "MAGI_SINGLE_TITLE_PLUS_EXISTING_EXACT_GATE")

    def test_magi_title_real_bundle_still_blocks(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/2",
            "[PSA10] Mewtwo 183/165 2枚 日本",
            10000,
            "151 Mewtwo",
        )
        ok, reason = magi_identity_check_v3(ask, MEWTWO)
        self.assertFalse(ok)
        self.assertEqual(reason, "multi_item_listing")

    def test_comc_text_row_accepts_exact_mewtwo_psa10(self):
        line = (
            "2023 Pokemon Scarlet & Violet - 151 [sv2a] - [Base] - Japanese | "
            "183 | Art Rare - Mewtwo [PSA 10 GEM MT] | Get SRP | $86.50 | Get SRP | 2"
        )
        ok, proof, price = comc_text_row_proof_v3(line, MEWTWO)
        self.assertTrue(ok)
        self.assertEqual(proof, "COMC_TEXT_VIEW_EXACT_ROW")
        self.assertEqual(price, 86.50)

    def test_comc_text_row_rejects_raw_same_card(self):
        line = (
            "2023 Pokemon Scarlet & Violet - 151 [sv2a] - [Base] - Japanese | "
            "183 | Art Rare - Mewtwo [Near Mint] | Get SRP | $18.71 | Get SRP | 5"
        )
        ok, reason, price = comc_text_row_proof_v3(line, MEWTWO)
        self.assertFalse(ok)
        self.assertEqual(reason, "psa10_unproven")
        self.assertIsNone(price)

    def test_comc_intrinsic_promo_number_can_prove_provider_set_alias(self):
        line = (
            "2025 Pokemon McDonald's Collection - Happy Meal Promos - Japanese | "
            "020/M-P | Pikachu [PSA 10 GEM MT] | Get SRP | $99.15 | 1"
        )
        ok, proof, price = comc_text_row_proof_v3(line, PIKACHU)
        self.assertTrue(ok)
        self.assertEqual(proof, "COMC_TEXT_VIEW_EXACT_ROW")
        self.assertEqual(price, 99.15)

    def test_comc_wrong_numeric_set_same_localid_still_rejects(self):
        line = (
            "2023 Pokemon Scarlet & Violet - Paradox Rift [PAR] - [Base] - Japanese | "
            "183 | Groudon [PSA 10 GEM MT] | Get SRP | $50 | 1"
        )
        ok, reason, _ = comc_text_row_proof_v3(line, GROUDON)
        self.assertFalse(ok)
        self.assertIn(reason, {"local_id_unproven", "set_unproven", "card_name_unproven"})


if __name__ == "__main__":
    unittest.main()
