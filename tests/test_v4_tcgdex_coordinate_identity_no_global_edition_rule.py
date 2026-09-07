import unittest

import watcher
import v4_tcgdex_detailed_variants as detailed


class NoGlobalEditionRuleTests(unittest.TestCase):
    def test_modern_listing_without_edition_has_no_synthetic_edition_requirement(self) -> None:
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/palkia",
            title="Palkia",
            current_price=50.0,
            source_type="fixed",
            grader="PSA",
            grade="10",
            card_set="Ultra Prism",
            card_number="165",
            language="English",
            year=2018,
            listing_text="Palkia #165 Ultra Prism English PSA 10",
        )
        self.assertNotIn("edition", detailed._expected_from_lot(lot))


if __name__ == "__main__":
    unittest.main()
