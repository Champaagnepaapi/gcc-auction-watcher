import unittest
from unittest.mock import patch

import watcher
import v4_tcgdex_coordinate_authoritative_name as target
import v4_tcgdex_two_of_three_backport as two_of_three


class ExactSetUniquenessTests(unittest.TestCase):
    def test_multiple_exact_set_ids_fail_closed(self) -> None:
        lot = watcher.Lot(
            url="x",
            title="Palkia",
            current_price=1.0,
            source_type="fixed",
            grader="PSA",
            grade="10",
            card_set="Ultra Prism",
            card_number="165",
            language="English",
        )
        with patch.object(two_of_three, "_exact_set_ids", return_value=("sm5", "other")):
            self.assertIsNone(target._recover_exact_set_coordinate(lot))


if __name__ == "__main__":
    unittest.main()
