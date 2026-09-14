import unittest

import v4_tcgdex_coordinate_authoritative_name as target


class CoordinateIdentityExampleTests(unittest.TestCase):
    def test_palkia_examples(self) -> None:
        self.assertTrue(target._coordinate_name_compatible("Palkia", "Palkia-GX"))
        self.assertTrue(target._coordinate_name_compatible("Palkia Rainbow", "Palkia-GX"))
        self.assertTrue(target._coordinate_name_compatible("Palkia FA", "Palkia-GX"))
        self.assertFalse(target._coordinate_name_compatible("Palkia V", "Palkia-GX"))

    def test_dark_blastoise_display_words_do_not_change_base_name(self) -> None:
        self.assertTrue(target._coordinate_name_compatible("Dark Blastoise Holo", "Dark Blastoise"))
        self.assertTrue(target._coordinate_name_compatible("Dark Blastoise Reverse Holo", "Dark Blastoise"))


if __name__ == "__main__":
    unittest.main()
