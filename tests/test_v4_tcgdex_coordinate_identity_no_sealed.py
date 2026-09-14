from pathlib import Path
import unittest


class NoSealedScopeTests(unittest.TestCase):
    def test_identity_module_does_not_add_sealed_product_logic(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8").casefold()
        self.assertNotIn("booster box", source)
        self.assertNotIn("sealed", source)


if __name__ == "__main__":
    unittest.main()
