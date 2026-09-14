import unittest

import watcher
import v4_tcgdex_coordinate_authoritative_name as target


class NoNameOnlyRecoveryTests(unittest.TestCase):
    def test_missing_set_or_number_cannot_use_coordinate_authority(self) -> None:
        base = dict(
            url="x",
            title="Palkia",
            current_price=1.0,
            source_type="fixed",
            grader="PSA",
            grade="10",
            language="English",
        )
        self.assertIsNone(target._recover_exact_set_coordinate(watcher.Lot(**base, card_set="", card_number="165")))
        self.assertIsNone(target._recover_exact_set_coordinate(watcher.Lot(**base, card_set="Ultra Prism", card_number="")))


if __name__ == "__main__":
    unittest.main()
