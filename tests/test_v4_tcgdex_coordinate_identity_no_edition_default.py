from pathlib import Path
import unittest


class NoEditionDefaultTests(unittest.TestCase):
    def test_module_never_infers_unlimited_from_absence(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8").casefold()
        self.assertNotIn('"unlimited"', source)
        self.assertNotIn('first_edition', source)


if __name__ == "__main__":
    unittest.main()
