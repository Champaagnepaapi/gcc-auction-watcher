import unittest

import japan_edge_hunter as japan
from v4_global_comc_hardening import (
    COMC_SORT_MODES,
    _page_url,
    _player_base,
    comc_table_row_proof,
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
PERSIAN = japan.Identity(
    name="Persian",
    set_name="Night Wanderer",
    number="75/64",
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


class ComcHardeningTests(unittest.TestCase):
    def test_player_base_strips_view_suffix(self):
        url = "https://www.comc.com/Players/Pokemon/Mewtwo/c78890/Cards/Pokemon%2Csn%2CvText"
        self.assertEqual(
            _player_base(url),
            "https://www.comc.com/Players/Pokemon/Mewtwo/c78890/Cards/Pokemon",
        )

    def test_sort_sweep_routes_are_explicit(self):
        base = "https://www.comc.com/Players/Pokemon/Mewtwo/c78890/Cards/Pokemon"
        self.assertEqual(COMC_SORT_MODES, ("sn", "ss", "sh", "sd"))
        self.assertEqual(_page_url(base, "sn", 1), base + "%2Csn%2CvText%2Ci100")
        self.assertEqual(_page_url(base, "ss", 1), base + "%2Css%2CvText%2Ci100")
        self.assertEqual(_page_url(base, "sh", 1), base + "%2Csh%2CvText%2Ci100")
        self.assertEqual(_page_url(base, "sd", 2), base + "%2Csd%2CvText%2Ci100%2Cp2")

    def test_unknown_sort_mode_fails_to_safe_default(self):
        base = "https://www.comc.com/Players/Pokemon/Mewtwo/c78890/Cards/Pokemon"
        self.assertEqual(_page_url(base, "bogus", 1), base + "%2Csn%2CvText%2Ci100")

    def test_mewtwo_local_id_plus_exact_set_is_exact(self):
        cells = [
            "2023 Pokemon Scarlet & Violet - 151 [sv2a] - [Base] - Japanese",
            "183",
            "Art Rare - Mewtwo [PSA 10 GEM MT]",
            "Get SRP",
            "$86.50",
            "Get SRP",
            "2",
        ]
        ok, proof = comc_table_row_proof(cells, MEWTWO)
        self.assertTrue(ok)
        self.assertEqual(proof, "COMC_EXACT_TABLE_ROW")

    def test_persian_wrong_set_same_local_id_rejected(self):
        cells = [
            "2023 Pokemon Scarlet & Violet - Shrouded Fable [SFA] - Japanese",
            "075",
            "Illustration Rare - Persian [PSA 10 GEM MT]",
            "N/A",
            "$62.35",
            "Get SRP",
            "1",
        ]
        ok, reason = comc_table_row_proof(cells, PERSIAN)
        self.assertFalse(ok)
        self.assertEqual(reason, "set_unproven")

    def test_promo_full_alphanumeric_number_can_survive_provider_set_alias(self):
        cells = [
            "2025 Pokemon McDonald's Collection - Happy Meal Promos - Japanese",
            "020/M-P",
            "Pikachu [PSA 10 GEM MT]",
            "N/A",
            "$99.15",
            "Get SRP",
            "1",
        ]
        ok, proof = comc_table_row_proof(cells, PIKACHU)
        self.assertTrue(ok)
        self.assertEqual(proof, "COMC_EXACT_TABLE_ROW")

    def test_raw_or_wrong_grade_never_becomes_exact(self):
        cells = [
            "2023 Pokemon Scarlet & Violet - 151 [sv2a] - [Base] - Japanese",
            "183",
            "Art Rare - Mewtwo [Near Mint]",
            "Get SRP",
            "$18.71",
            "Get SRP",
            "5",
        ]
        ok, reason = comc_table_row_proof(cells, MEWTWO)
        self.assertFalse(ok)
        self.assertEqual(reason, "psa10_unproven")


if __name__ == "__main__":
    unittest.main()
