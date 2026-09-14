import unittest

import v4_tcgdex_coordinate_authoritative_name as target


class DisplayTokenTests(unittest.TestCase):
    def test_display_suffixes_are_bounded_and_trailing(self) -> None:
        self.assertEqual(target._strip_display_suffixes(("palkia", "full", "art")), ("palkia",))
        self.assertEqual(target._strip_display_suffixes(("palkia", "rainbow")), ("palkia",))
        self.assertEqual(target._strip_display_suffixes(("rainbow", "energy")), ("rainbow", "energy"))


if __name__ == "__main__":
    unittest.main()
