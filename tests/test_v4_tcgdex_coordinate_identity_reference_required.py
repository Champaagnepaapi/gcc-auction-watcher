import unittest

import watcher
import v4_tcgdex_coordinate_authoritative_name as target


class PrintedReferenceRequiredTests(unittest.TestCase):
    def test_no_printed_reference_means_no_coordinate_recovery(self) -> None:
        lot = watcher.Lot(
            url="x",
            title="Palkia",
            current_price=1.0,
            source_type="fixed",
            grader="PSA",
            grade="10",
            card_set="Ultra Prism",
            card_number="",
            language="English",
        )
        self.assertIsNone(target._recover_exact_set_coordinate(lot))


if __name__ == "__main__":
    unittest.main()
