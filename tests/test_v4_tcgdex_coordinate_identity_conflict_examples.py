import unittest

import v4_tcgdex_coordinate_authoritative_name as target


class StructuralConflictExamplesTests(unittest.TestCase):
    def test_v_gx_and_ex_v_conflicts(self) -> None:
        self.assertFalse(target._coordinate_name_compatible("Palkia V", "Palkia-GX"))
        self.assertFalse(target._coordinate_name_compatible("Mew ex", "Mew V"))
        self.assertFalse(target._coordinate_name_compatible("Charizard VMAX", "Charizard VSTAR"))


if __name__ == "__main__":
    unittest.main()
