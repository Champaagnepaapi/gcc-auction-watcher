from pathlib import Path
import unittest


class NoSetGuessTests(unittest.TestCase):
    def test_module_uses_existing_exact_set_resolver(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8")
        self.assertIn("two_of_three._exact_set_ids", source)
        self.assertNotIn("difflib", source)


if __name__ == "__main__":
    unittest.main()
