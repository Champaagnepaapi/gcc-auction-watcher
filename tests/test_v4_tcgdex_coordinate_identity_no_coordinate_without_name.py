import unittest

import watcher
import v4_tcgdex_coordinate_authoritative_name as target


class BaseNameRequiredTests(unittest.TestCase):
    def test_blank_name_does_not_recover_from_number_alone(self) -> None:
        lot = watcher.Lot(url="x", title="", current_price=1.0, source_type="fixed", grader="PSA", grade="10", card_set="Ultra Prism", card_number="165", language="English")
        self.assertIsNone(target._recover_exact_set_coordinate(lot))


if __name__ == "__main__":
    unittest.main()
