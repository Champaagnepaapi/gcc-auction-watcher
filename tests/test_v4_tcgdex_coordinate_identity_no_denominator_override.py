import unittest

import v4_tcgdex_coordinate_authoritative_name as target


class NoDenominatorOverrideTests(unittest.TestCase):
    def test_explicit_reference_wins_over_catalog_count_string(self) -> None:
        card = {"localId": "165", "set": {"cardCount": {"official": 156}}}
        self.assertEqual(target._catalog_full_number(card, "165/999"), "165/999")


if __name__ == "__main__":
    unittest.main()
