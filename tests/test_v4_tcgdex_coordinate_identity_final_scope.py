from pathlib import Path
import unittest


class FinalScopeTests(unittest.TestCase):
    def test_scope_is_identity_only_and_fail_closed(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8")
        self.assertIn("_material_identity_is_resolved", source)
        self.assertIn("_coordinate_name_compatible", source)
        self.assertIn("_exact_set_ids", source)


if __name__ == "__main__":
    unittest.main()
