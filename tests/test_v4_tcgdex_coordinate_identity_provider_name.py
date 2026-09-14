import unittest

import v4_tcgdex_coordinate_authoritative_name as target


class CanonicalProviderNameTests(unittest.TestCase):
    def test_coordinate_bridge_prefers_official_form_over_omitted_listing_form(self) -> None:
        self.assertTrue(target._coordinate_name_compatible("Palkia", "Palkia-GX"))
        self.assertFalse(target._coordinate_name_compatible("Dialga", "Palkia-GX"))


if __name__ == "__main__":
    unittest.main()
