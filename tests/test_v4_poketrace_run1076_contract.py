from __future__ import annotations

import unittest

import v4_poketrace_market_retrieval as retrieval


class Run1076RetrievalContractTests(unittest.TestCase):
    def test_market_game_is_explicit_for_supported_exact_languages(self):
        self.assertEqual(retrieval._exact_market_game("en"), "pokemon")
        self.assertEqual(retrieval._exact_market_game("ja"), "pokemon-japanese")
        self.assertEqual(retrieval._exact_market_game("jp"), "pokemon-japanese")

    def test_unsupported_exact_languages_do_not_silently_map_to_english_market(self):
        for code in ("fr", "de", "it", "es", "ko", "zh-tw", "th", ""):
            with self.subTest(code=code):
                self.assertEqual(retrieval._exact_market_game(code), "")


if __name__ == "__main__":
    unittest.main()
