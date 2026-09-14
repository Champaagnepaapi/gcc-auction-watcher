import unittest

import v4_tcgdex_coordinate_authoritative_name as target


class InternalTokenPreservationTests(unittest.TestCase):
    def test_internal_words_are_never_treated_as_display_suffix(self) -> None:
        self.assertFalse(target._coordinate_name_compatible("Dark Charizard", "Charizard"))
        self.assertFalse(target._coordinate_name_compatible("Brock Rhydon", "Brock Ninetales"))


if __name__ == "__main__":
    unittest.main()
