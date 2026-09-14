import unittest

import watcher
import v4_tcgdex_detailed_variants as detailed


class FirstEditionScopeTests(unittest.TestCase):
    def test_no_first_edition_word_means_no_listing_edition_claim(self) -> None:
        lot = watcher.Lot(
            url="x",
            title="Dark Blastoise",
            current_price=1.0,
            source_type="fixed",
            grader="PSA",
            grade="10",
            card_set="Team Rocket",
            card_number="3/82",
            language="English",
        )
        self.assertNotIn("edition", detailed._expected_from_lot(lot))


if __name__ == "__main__":
    unittest.main()
