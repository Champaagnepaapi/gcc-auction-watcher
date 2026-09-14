from pathlib import Path
import unittest


class NoFinishDefaultTests(unittest.TestCase):
    def test_module_never_defaults_missing_finish_to_normal(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8")
        self.assertNotIn('expected_finish = "non_holo"', source)
        self.assertNotIn('expected_finish = "holo"', source)


if __name__ == "__main__":
    unittest.main()
