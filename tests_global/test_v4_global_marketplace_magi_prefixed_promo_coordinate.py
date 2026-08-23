from __future__ import annotations

import unittest

import v4_global_marketplace_magi_prefixed_promo_coordinate as prefixed


class MagiPrefixedPromoCoordinateTests(unittest.TestCase):
    def test_cll_coordinate_requires_standalone_echo(self):
        self.assertEqual(
            prefixed._prefixed_coordinate("(CLL) PROMO CLL007/032"),
            ("7/32", "CLL", "magi_native_prefixed_promo_coordinate_parsed"),
        )

    def test_clk_coordinate_requires_standalone_echo(self):
        self.assertEqual(
            prefixed._prefixed_coordinate("Classic カメックス (CLK) PROMO CLK003/032"),
            ("3/32", "CLK", "magi_native_prefixed_promo_coordinate_parsed"),
        )

    def test_embedded_prefix_alone_is_not_enough(self):
        self.assertEqual(
            prefixed._prefixed_coordinate("PROMO CLL007/032"),
            ("", "", "set_code_unproven"),
        )

    def test_unreviewed_prefix_is_not_accepted(self):
        self.assertEqual(
            prefixed._prefixed_coordinate("(ABC) PROMO ABC007/032"),
            ("", "", "set_code_unproven"),
        )

    def test_conflicting_coordinates_remain_ambiguous(self):
        self.assertEqual(
            prefixed._prefixed_coordinate("(CLL) CLL007/032 (CLK) CLK003/032"),
            ("", "", "collector_number_ambiguous"),
        )


if __name__ == "__main__":
    unittest.main()
