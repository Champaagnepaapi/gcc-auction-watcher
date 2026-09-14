import unittest

import v4_tcgdex_coordinate_authoritative_name as target


class CoordinateIdentitySuffixBoundaryTests(unittest.TestCase):
    def test_display_words_are_only_removed_at_the_end(self) -> None:
        self.assertFalse(target._coordinate_name_compatible("Rainbow Energy", "Energy"))
        self.assertFalse(target._coordinate_name_compatible("Holo Caster", "Caster"))

    def test_unrelated_extra_words_are_not_dropped(self) -> None:
        self.assertFalse(target._coordinate_name_compatible("Palkia Alternate", "Palkia-GX"))


if __name__ == "__main__":
    unittest.main()
