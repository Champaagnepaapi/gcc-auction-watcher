from pathlib import Path
import unittest


class CoordinateIdentityMarketSemanticsTests(unittest.TestCase):
    def test_identity_module_does_not_classify_market_evidence(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8")
        self.assertNotIn("SOLD", source)
        self.assertNotIn("ACTIVE_AUCTION", source)
        self.assertNotIn("fair_value", source)


if __name__ == "__main__":
    unittest.main()
