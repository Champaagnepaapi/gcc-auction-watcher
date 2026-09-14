import unittest

import v4_tcgdex_detailed_variants as detailed


class DetailedLanguageScopeTests(unittest.TestCase):
    def test_wrong_language_variant_is_not_usable(self) -> None:
        state, entries = detailed.sanitize_variants_detailed(
            [{"type": "holo", "languages": ["fr"]}], language_code="en"
        )
        self.assertEqual(state, "NO_LANGUAGE_VARIANT")
        self.assertEqual(entries, ())


if __name__ == "__main__":
    unittest.main()
