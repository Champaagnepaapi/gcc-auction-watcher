from pathlib import Path
import unittest


class NoNewSetAliasesTests(unittest.TestCase):
    def test_coordinate_module_has_no_hardcoded_set_ids(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8")
        for set_id in ("sm5", "base5", "base6", "swsh12"):
            self.assertNotIn(f'"{set_id}"', source)


if __name__ == "__main__":
    unittest.main()
