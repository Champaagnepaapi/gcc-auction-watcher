import unittest

import v4_tcgdex_coordinate_authoritative_name as target


class StructuralOmissionExamplesTests(unittest.TestCase):
    def test_missing_form_on_one_side_is_allowed(self) -> None:
        self.assertTrue(target._coordinate_name_compatible("Palkia", "Palkia-GX"))
        self.assertTrue(target._coordinate_name_compatible("Mew", "Mew ex"))
        self.assertTrue(target._coordinate_name_compatible("Charizard", "Charizard VMAX"))


if __name__ == "__main__":
    unittest.main()
