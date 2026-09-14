import unittest

import v4_tcgdex_coordinate_authoritative_name as target


class ExactNameCompatibilityTests(unittest.TestCase):
    def test_exact_names_are_unchanged(self) -> None:
        self.assertTrue(target._coordinate_name_compatible("Palkia-GX", "Palkia-GX"))
        self.assertTrue(target._coordinate_name_compatible("Dark Blastoise", "Dark Blastoise"))


if __name__ == "__main__":
    unittest.main()
