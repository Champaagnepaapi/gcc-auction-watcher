from pathlib import Path
import unittest


class NoGlobalSuffixDropTests(unittest.TestCase):
    def test_display_suffix_logic_lives_only_in_coordinate_recovery_module(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8")
        self.assertIn("_strip_display_suffixes", source)
        self.assertIn("_recover_exact_set_coordinate", source)


if __name__ == "__main__":
    unittest.main()
