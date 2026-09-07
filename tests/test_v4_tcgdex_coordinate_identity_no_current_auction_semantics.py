from pathlib import Path
import unittest


class NoAuctionStateChangeTests(unittest.TestCase):
    def test_identity_module_has_no_countdown_or_auction_state_logic(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8").casefold()
        self.assertNotIn("countdown", source)
        self.assertNotIn("ending_soon", source)


if __name__ == "__main__":
    unittest.main()
