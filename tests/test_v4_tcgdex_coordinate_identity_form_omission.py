import unittest

import v4_tcgdex_coordinate_authoritative_name as target


class CardFormOmissionTests(unittest.TestCase):
    def test_one_missing_form_is_omission_but_two_different_forms_conflict(self) -> None:
        self.assertTrue(target._coordinate_name_compatible("Mew", "Mew ex"))
        self.assertTrue(target._coordinate_name_compatible("Mew ex", "Mew"))
        self.assertFalse(target._coordinate_name_compatible("Mew V", "Mew ex"))


if __name__ == "__main__":
    unittest.main()
