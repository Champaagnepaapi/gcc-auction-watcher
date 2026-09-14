import unittest

import v4_tcgdex_coordinate_authoritative_name as target


class SpellingBridgeTests(unittest.TestCase):
    def test_small_spelling_noise_only_after_coordinate_name_reduction(self) -> None:
        self.assertTrue(target._coordinate_name_compatible("Brock Ninetales", "Brock's Ninetales"))
        self.assertTrue(target._coordinate_name_compatible("Ninetalez", "Ninetales"))
        self.assertFalse(target._coordinate_name_compatible("Ninetales", "Rhydon"))


if __name__ == "__main__":
    unittest.main()
