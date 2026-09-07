from pathlib import Path
import unittest


class SetScopedLocalIdTests(unittest.TestCase):
    def test_card_fetch_is_scoped_to_resolved_set(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8")
        self.assertIn("/sets/{set_id}/{local_id}", source)
        self.assertNotIn("/cards?localId", source)


if __name__ == "__main__":
    unittest.main()
