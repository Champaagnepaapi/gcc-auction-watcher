import unittest
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_coordinate_authoritative_name as target
import v4_tcgdex_two_of_three_backport as two_of_three


class CoordinateIdentityTransientTests(unittest.TestCase):
    def test_transient_coordinate_fetch_is_not_clean_no_match(self) -> None:
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
        with patch.object(two_of_three, "_exact_set_ids", return_value=("sm5",)), patch.object(
            canonical, "_json_get", return_value=(503, {}, {})
        ):
            result = target._recover_exact_set_coordinate(lot)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "ERROR")


if __name__ == "__main__":
    unittest.main()
