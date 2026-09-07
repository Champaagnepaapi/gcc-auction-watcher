import unittest

import v4_tcgdex_coordinate_authoritative_name as target


class TargetAmbiguityReasonTests(unittest.TestCase):
    def test_target_reason_is_narrow(self) -> None:
        self.assertEqual(target._TARGET_AMBIGUOUS_REASONS, {"TCGdex unique-coordinate printed number/denominator is not unique"})


if __name__ == "__main__":
    unittest.main()
