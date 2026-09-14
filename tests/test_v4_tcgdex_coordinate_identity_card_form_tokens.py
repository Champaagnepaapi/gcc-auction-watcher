import unittest

import v4_tcgdex_coordinate_authoritative_name as target


class CardFormTokenTests(unittest.TestCase):
    def test_common_structural_forms_are_explicitly_bounded(self) -> None:
        forms = {form for _, form in target._CARD_FORM_SUFFIXES}
        self.assertTrue({"gx", "v", "vmax", "vstar", "ex"}.issubset(forms))
        self.assertNotIn("holo", forms)
        self.assertNotIn("rainbow", forms)


if __name__ == "__main__":
    unittest.main()
