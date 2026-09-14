import unittest

import v4_tcgdex_coordinate_authoritative_name as target


class PromoNumberTests(unittest.TestCase):
    def test_existing_namespace_reference_is_preserved(self) -> None:
        card = {"localId": "SM214", "set": {"cardCount": {"official": 0}}}
        self.assertEqual(target._catalog_full_number(card, "SM214"), "SM214")
        self.assertEqual(target._catalog_full_number(card, "214/S-P"), "214/S-P")


if __name__ == "__main__":
    unittest.main()
