import unittest

import v4_tcgdex_coordinate_authoritative_name as target


class CoordinateDenominatorTests(unittest.TestCase):
    def test_catalog_full_number_only_fills_missing_denominator(self) -> None:
        card = {
            "localId": "165",
            "set": {"cardCount": {"official": 156}},
        }
        self.assertEqual(target._catalog_full_number(card, "165"), "165/156")
        self.assertEqual(target._catalog_full_number(card, "165/156"), "165/156")
        self.assertEqual(target._catalog_full_number(card, "165/157"), "165/157")


if __name__ == "__main__":
    unittest.main()
