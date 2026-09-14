from pathlib import Path
import unittest


class SetNumberPriorityTests(unittest.TestCase):
    def test_module_requires_set_and_reference_before_name_bridge(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8")
        self.assertIn("if not (language_code and listing_set and reference and listing_name)", source)


if __name__ == "__main__":
    unittest.main()
