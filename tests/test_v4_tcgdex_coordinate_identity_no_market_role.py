from pathlib import Path
import unittest


class IdentityOnlyScopeTests(unittest.TestCase):
    def test_module_does_not_define_market_role(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8").casefold()
        self.assertNotIn("valuation", source)
        self.assertNotIn("opportunity", source)


if __name__ == "__main__":
    unittest.main()
