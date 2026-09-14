import unittest

import v4_tcgdex_coordinate_authoritative_name as target


class FullArtSemanticsTests(unittest.TestCase):
    def test_full_art_is_presentation_suffix_not_card_form(self) -> None:
        forms = {form for _, form in target._CARD_FORM_SUFFIXES}
        self.assertNotIn("full_art", forms)
        self.assertIn(("full", "art"), target._DISPLAY_SUFFIXES)


if __name__ == "__main__":
    unittest.main()
