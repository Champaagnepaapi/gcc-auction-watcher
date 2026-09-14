import unittest
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_coordinate_authoritative_name as target
import v4_tcgdex_two_of_three_backport as two_of_three


class CoordinateLanguageTests(unittest.TestCase):
    def test_recovery_queries_the_listing_language_catalogue(self) -> None:
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
        card = {
            "id": "sm5-165",
            "localId": "165",
            "name": "Palkia-GX",
            "set": {"id": "sm5", "name": "Ultra Prism", "cardCount": {"official": 156}},
            "variants": {"holo": True, "normal": False, "reverse": False},
            "pricing": {},
        }
        with patch.object(two_of_three, "_exact_set_ids", return_value=("sm5",)), patch.object(
            canonical, "_json_get", return_value=(200, card, {})
        ) as getter:
            result = target._recover_exact_set_coordinate(lot)
        self.assertIsNotNone(result)
        self.assertIn("/en/sets/sm5/", getter.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
