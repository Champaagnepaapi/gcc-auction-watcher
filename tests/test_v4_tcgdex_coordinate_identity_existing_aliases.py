from pathlib import Path
import unittest


class ExistingAliasPreservationTests(unittest.TestCase):
    def test_module_reuses_exact_set_resolver_instead_of_defining_alias_table(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8")
        self.assertNotIn("ExactSetAlias", source)
        self.assertIn("two_of_three._exact_set_ids", source)


if __name__ == "__main__":
    unittest.main()
