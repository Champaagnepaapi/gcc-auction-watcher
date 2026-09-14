from pathlib import Path
import unittest


class CoordinateIdentityReadOnlyTests(unittest.TestCase):
    def test_new_identity_layer_contains_no_transaction_actions(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8").casefold()
        for forbidden in ("checkout(", "place_bid(", "purchase(", "payment("):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
