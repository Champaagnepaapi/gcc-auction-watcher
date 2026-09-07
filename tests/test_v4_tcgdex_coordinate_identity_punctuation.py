import unittest

import v4_tcgdex_coordinate_authoritative_name as target


class PunctuationTests(unittest.TestCase):
    def test_hyphenated_card_form_is_equivalent(self) -> None:
        self.assertTrue(target._coordinate_name_compatible("Palkia GX", "Palkia-GX"))


if __name__ == "__main__":
    unittest.main()
