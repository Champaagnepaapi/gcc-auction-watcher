import unittest
from unittest.mock import patch

import japan_edge_hunter as japan

from v4_global_comc_hardening_v2 import (
    COMC_EXACT_SET_RETRIEVAL_ROUTES,
    COMC_PSA10_SUFFIX,
    _exact_set_retrieval_url,
    _graded_page_url,
    _query_plan,
    _retrieval_player_label,
    resolve_comc_player_base_v2,
)


GROUDON = japan.Identity(
    "Groudon",
    "Raging Surf",
    "69/62",
    "Japanese",
    "PSA",
    "10",
    2023,
)


class FakeSetFacetPage:
    def __init__(self):
        self.url = ""
        self.visited = []

    def goto(self, url, **_kwargs):
        self.url = url
        self.visited.append(url)

    def wait_for_timeout(self, _milliseconds):
        return None

    def evaluate(self, _script):
        if "Raging_Surf_sv3a" in self.url:
            return [
                {
                    "href": "https://www.comc.com/Players/Pokemon/Groudon/c81391/Cards/Pokemon",
                    "text": "Groudon (3)",
                }
            ]
        return []


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

    def test_raging_surf_japanese_route_is_exact_and_version_bounded(self):
        route = _exact_set_retrieval_url(GROUDON)
        self.assertEqual(
            route,
            COMC_EXACT_SET_RETRIEVAL_ROUTES[("raging surf", "japanese", 2023)],
        )
        self.assertIn("Raging_Surf_sv3a", route)
        self.assertTrue(route.endswith("_Japanese"))

    def test_same_set_wrong_language_cannot_use_japanese_route(self):
        english = japan.Identity(
            "Groudon", "Raging Surf", "69/62", "English", "PSA", "10", 2023
        )
        self.assertIsNone(_exact_set_retrieval_url(english))

    def test_groudon_resolves_from_exact_set_facet_after_global_indexes_miss(self):
        page = FakeSetFacetPage()
        with patch(
            "v4_global_comc_hardening_v2.v4.resolve_comc_player_base",
            return_value=(None, "PLAYER_UNRESOLVED"),
        ):
            base, proof = resolve_comc_player_base_v2(page, GROUDON)

        self.assertEqual(
            base,
            "https://www.comc.com/Players/Pokemon/Groudon/c81391/Cards/Pokemon",
        )
        self.assertEqual(proof, "PLAYER_LINK_EXACT_SET_ROUTE_COUNT_STRIPPED")
        self.assertTrue(any("Raging_Surf_sv3a" in url for url in page.visited))

    def test_wrong_player_on_exact_set_page_does_not_resolve(self):
        page = FakeSetFacetPage()
        persian = japan.Identity(
            "Persian", "Raging Surf", "69/62", "Japanese", "PSA", "10", 2023
        )
        with patch(
            "v4_global_comc_hardening_v2.v4.resolve_comc_player_base",
            return_value=(None, "PLAYER_UNRESOLVED"),
        ):
            base, proof = resolve_comc_player_base_v2(page, persian)
        self.assertIsNone(base)
        self.assertEqual(proof, "PLAYER_UNRESOLVED")


if __name__ == "__main__":
    unittest.main()
