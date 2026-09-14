from pathlib import Path
import unittest


class NoCrossLanguageTests(unittest.TestCase):
    def test_recovery_uses_listing_language_for_exact_card_endpoint(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8")
        self.assertIn("/{language_code}/sets/{set_id}/{local_id}", source)


if __name__ == "__main__":
    unittest.main()
