import unittest

import v4_tcgdex_coordinate_authoritative_name as target


class SuffixConflictTests(unittest.TestCase):
    def test_display_suffix_is_removed_before_structural_form_comparison(self) -> None:
        self.assertFalse(target._coordinate_name_compatible("Palkia V Rainbow", "Palkia-GX"))
        self.assertTrue(target._coordinate_name_compatible("Palkia GX Rainbow", "Palkia-GX"))


if __name__ == "__main__":
    unittest.main()
