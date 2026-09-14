from pathlib import Path
import unittest


class NoFuzzySearchTests(unittest.TestCase):
    def test_no_fuzzy_or_translation_query_is_added(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8").casefold()
        for token in ("levenshtein", "translate(", "substring", "fuzzy search"):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
