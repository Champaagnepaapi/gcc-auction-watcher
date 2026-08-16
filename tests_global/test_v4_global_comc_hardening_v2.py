import unittest

from v4_global_comc_hardening_v2 import (
    COMC_PSA10_SUFFIX,
    _graded_page_url,
    _query_plan,
    _retrieval_player_label,
)


class ComcHardeningV2Tests(unittest.TestCase):
    def test_psa10_filter_is_explicit_and_keeps_sort(self):
        base = "https://www.comc.com/Players/Pokemon/Mewtwo/c78890/Cards/Pokemon"
        self.assertEqual(
            _graded_page_url(base, "ss", 1),
            base + "%2Css%2CvText%2Ci100" + COMC_PSA10_SUFFIX,
        )
        self.assertEqual(
            _graded_page_url(base, "sd", 2),
            base + "%2Csd%2CvText%2Ci100" + COMC_PSA10_SUFFIX + "%2Cp2",
        )

    def test_query_plan_runs_psa10_filters_before_broad_fallback(self):
        base = "https://www.comc.com/Players/Pokemon/Persian/c81896/Cards/Pokemon"
        plan = _query_plan(base, ("sn", "ss"))
        self.assertEqual([scope for _, scope, _ in plan], [
            "PSA10_FILTER",
            "PSA10_FILTER",
            "BROAD_FALLBACK",
            "BROAD_FALLBACK",
        ])
        self.assertTrue(plan[0][2].endswith(COMC_PSA10_SUFFIX))
        self.assertNotIn("aGraded", plan[-1][2])

    def test_player_facet_count_is_removed_for_retrieval_only(self):
        self.assertEqual(_retrieval_player_label("Groudon (3)"), "groudon")
        self.assertEqual(_retrieval_player_label("Mewtwo (1,234)"), "mewtwo")

    def test_non_count_suffix_is_not_removed(self):
        self.assertEqual(_retrieval_player_label("Groudon EX"), "groudon ex")
        self.assertNotEqual(_retrieval_player_label("Groudon EX"), "groudon")


if __name__ == "__main__":
    unittest.main()
