from pathlib import Path
import unittest


class CoordinateFirstTests(unittest.TestCase):
    def test_name_bridge_is_inside_exact_set_coordinate_recovery(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8")
        self.assertIn("two_of_three._exact_set_ids", source)
        self.assertIn("generalized._reference_candidates", source)
        self.assertIn("_coordinate_name_compatible", source)


if __name__ == "__main__":
    unittest.main()
